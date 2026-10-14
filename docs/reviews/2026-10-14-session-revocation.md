# 2026-10-14 인증 번들 간 세션 폐기 보강

## 발견과 범위

최신 운영 UI의 공개 화면 시험 90개는 통과했지만, 별도 실제 HTTP 검사에서 로그인 후 로그아웃한 쿠키를 직접 다시 보내면 내부·공개 보호 API가 모두 200을 반환했다. 브라우저 cookie 삭제·새 탭 무인증과 기존 cookie 재사용 거절은 서로 다른 조건이다. 독립 auth 모듈 두 개로 같은 반례를 재현했다(기존 구현 RED 1건).

Next.js Proxy는 Route Handler와 공유 모듈·전역 메모리에 의존하면 안 된다. [공식 Proxy 문서](https://nextjs.org/docs/app/api-reference/file-conventions/proxy)의 실행 경계에 맞춰, 지원하는 단일 Linux UI 컨테이너 안의 private 파일 상태를 여러 번들이 읽도록 변경한다. 운영 backend·Geo·공용 Docker daemon 재시작은 이 변경의 조건이 아니다.

## 설계

- session ID별 marker를 디스크에 남기고 검증 시 marker 존재를 확인한다. 폐기 목록 전체를 Node 메모리에 유지하지 않는다.
- 컨테이너의 private nonce를 cookie 서명 namespace에 포함한다. Node 프로세스를 재시작해도 같은 상태가 보존되며, 상태 디렉터리가 새로 만들어지면 이전 cookie를 모두 거절한다. 첫 반영 시 기존 cookie는 다시 로그인해야 한다.
- marker는 만료 hour 버킷에 저장하고 만료된 버킷만 streaming 목록으로 청소한다. provider 데이터·미디어를 삭제하지 않는다.
- 상태를 읽거나 기록할 수 없으면 인증을 허용하거나 logout 성공을 반환하지 않는다. 상태 I/O에는 대기 상한을 둔다.
- 기본 경로는 UI 컨테이너 임시 파일시스템이다. 동일 컨테이너의 Proxy·Route Handler·여러 Node 프로세스만 지원한다. 여러 컨테이너/호스트로 확장할 때는 같은 상태·nonce를 공유할 저장소와 별도 검증이 필요하다.

## 검증 상태

현재 초안이다. 독립 번들 회귀, 동시 nonce 초기화, 상태 손실·오류·expiry 경계, 실제 production HTTP cookie 재사용 거절, 두 명의 적대 리뷰, 새 운영 이미지의 live/UI E2E까지 확인한 뒤 소스 및 운영 완료 상태를 갱신한다. 이전 이미지의 90 PASS를 새 이미지의 PASS로 합산하지 않는다.

기존 배포의 태그 명령 UNKNOWN은 별도 원문 기록을 보존한다. 이번 변경으로 과거 명령 완료를 만들어내거나 공용 daemon을 재시작하지 않는다.
