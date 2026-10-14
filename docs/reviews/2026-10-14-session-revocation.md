# 2026-10-14 인증 번들 간 세션 폐기 보강

## 발견과 범위

최신 운영 UI의 공개 화면 시험 90개는 통과했지만, 별도 실제 HTTP 검사에서 로그인 후 로그아웃한 쿠키를 직접 다시 보내면 내부·공개 보호 API가 모두 200을 반환했다. 브라우저 cookie 삭제·새 탭 무인증과 기존 cookie 재사용 거절은 서로 다른 조건이다. 독립 auth 모듈 두 개로 같은 반례를 재현했다(기존 구현 RED 1건).

Next.js Proxy는 Route Handler와 공유 모듈·전역 메모리에 의존하면 안 된다. [공식 Proxy 문서](https://nextjs.org/docs/app/api-reference/file-conventions/proxy)의 실행 경계에 맞춰, 지원하는 단일 Linux UI 컨테이너 안의 private 파일 상태를 여러 번들이 읽도록 변경한다. 운영 backend·Geo·공용 Docker daemon 재시작은 이 변경의 조건이 아니다.

## 설계

- session ID별 marker를 디스크에 남기고 검증 시 marker 존재를 확인한다. 폐기 목록 전체를 Node 메모리에 유지하지 않는다.
- 컨테이너의 private nonce를 cookie 서명 namespace에 포함한다. Node 프로세스를 재시작해도 같은 상태가 보존되며, 상태 디렉터리가 새로 만들어지면 이전 cookie를 모두 거절한다. 첫 반영 시 기존 cookie는 다시 로그인해야 한다.
- marker는 만료 hour 버킷에 저장하고 만료된 버킷만 streaming 목록으로 청소한다. provider 데이터·미디어를 삭제하지 않는다.
- 상태를 읽거나 기록할 수 없으면 인증을 허용하거나 logout 성공을 반환하지 않는다. 각 상태 helper의 호출자 대기는 2초로 제한한다. syscall 취소를 주장하지 않으며, 고정 server bundle별 미완 작업 32개 상한을 실제 작업 settle까지 유지한다. 포화 상태는 즉시 인증 거절/503으로 반환한다.
- 기본 경로는 UI 컨테이너 임시 파일시스템이다. 동일 컨테이너의 Proxy·Route Handler·여러 Node 프로세스만 지원한다. 여러 컨테이너/호스트로 확장할 때는 같은 상태·nonce를 공유할 저장소와 별도 검증이 필요하다. nonce를 보존한 채 개별 marker만 유실하면 폐기가 사라질 수 있으므로 상태 전체를 함께 보존하고, 부분 복원 뒤에는 nonce를 새로 만들어 기존 세션을 전부 무효화해야 한다. 총 호스트 RSS·디스크 사용량의 감소를 보장하는 수치로 해석하지 않는다.

## 검증 상태

전체 frontend **376 PASS**, lint/type/production build PASS다. 독립 번들 폐기·64개 초기화에서 32개 입장/32개 포화 거절·상태 손실·오류·expiry·영구 I/O 100+100 요청과 회복을 확인했다. 실제 Next production compiled Proxy/Route Handler를 소유 테스트 HTTP backend에 연결한 12개 검사에서 cookie 재사용 API 401·페이지 로그인 redirect·다른 세션 보존·Node 재시작·상태 손실 복구·오류 503을 확인했다. 이는 운영 API/provider 검증과 구분한다. 최초 로컬 HTTP 하니스는 backend 환경 변수 이름을 잘못 지정해 실패했고 올바른 BACKEND_ORIGIN으로 수정한 뒤 실행했다. 두 명의 리뷰 및 새 운영 이미지 live/UI 결과는 아직 완료로 표시하지 않는다. 이전 이미지의 90 PASS를 새 이미지의 PASS로 합산하지 않는다.

기존 배포의 태그 명령 UNKNOWN은 별도 원문 기록을 보존한다. 이번 변경으로 과거 명령 완료를 만들어내거나 공용 daemon을 재시작하지 않는다.

최초 두 리뷰의 P2는 2초 이후에도 원 I/O가 100→200개 누적되는 경로였다. lazy admission과 실제 settle 전 슬롯 유지로 수정했고, 만료 버킷 삭제도 opendir·marker별 unlink·rmdir로 바꾸어 recursive rm의 전체 목록 배열에 의존하지 않는다. BFF는 Proxy 판정과 별도로 유효 세션을 확인하고 실패 시 key 주입·upstream 호출 전에 401을 반환한다.

추가 독립 리뷰 A가 nonce write/fsync/close 실패 후 temp 파일이 남는 P2를 실제 소유 FileHandle 실패 3회로 재현했다. 생성 temp의 write·fsync·close·link 전체를 outer finally 정리로 감쌌다. bundle 안에서 초기화를 하나의 Promise로 직렬화하고 temp 삭제도 실패하면 기존 own temp를 회수하기 전 새 inode를 만들지 않는다. fsync 실패 3회 temp 0, fsync+unlink 실패 3회 temp 1, I/O 복구 뒤 temp 0 및 새 쿠키 검증을 회귀로 확인했다. abrupt process crash·분산 저장소의 부분 유실을 보장하는 수치로 확대하지 않는다.

## 첫 새 운영 이미지의 UI 검증과 후속 가용성 보강

R4 이미지의 실제 운영 LAN/public login200·오류401·logout200·원 cookie replay401 및 원 cookie 재사용 browser 회귀를 확인했다. 첫 전체 UI 실행은 **90 PASS / 1 FAIL / skip0 / retry0**였다. 390px 전체 메뉴 이동 중 login-events401로 로그인 경로에 이동했고 다음 주요 응답을 기다리다 75초 timeout이 발생했다. 정확한 운영 401 원인이 FS 입장 포화였는지는 별도 직접 증명하지 않았다.

소스에서는 상태 I/O 실패·포화를 invalid cookie와 합쳐 401로 처리하는 경로가 확인됐다. SessionStatus의 valid/invalid/unavailable을 구분하고 Proxy·BFF는 unavailable에 503/Retry-After를 반환하여 cookie 삭제·로그인 redirect 없이 재시도한다. 보호 body/upstream/key는 계속 차단한다. 잘못된 서명·만료·폐기 cookie의 401/로그인 redirect는 보존한다.

고정 bundle의 미완 I/O 입장 상한은 정상 sidebar prefetch와 설정 화면의 병렬 요청 여유를 고려해 32로 조정했다. 64개 초기화에서32허용/32거절, 영구 I/O100+100 요청에서도 원 작업32유지 및 실제 settle 뒤 회복을 검증했다. 최신 전체 frontend376·lint/type/build와 production compiled HTTP12를 확인했다. 첫 실패 실행은 보존하며 새 운영 이미지의91개 전부 통과 전 최종 성공으로 표시하지 않는다.
