# 프론트엔드·브라우저 하니스 도구 계약

저장소 .nvmrc는 Node22.23.1을 선택한다. frontend와 tests는 각각 private package anchor이며 packageManager=npm@12.0.1, engines.node=22.23.1/npm=12.0.1, anchor .npmrc=engine-strict=true로 맞춘다. 두 lock은 root 엔진 metadata만 변경하며 의존성 graph·C11 vendor/원장·공개 라이브러리 버전은 그대로다.

CI는 기존 검사 step 상대순서를 유지한다. 기존 첫 설치 step 안에서 frontend packageManager의 실제 npm12를 global 선택하고 npm ci --engine-strict를 실행한다. 기존 strict-peer-deps/no-audit/no-fund를 그대로 유지하며 후반 tests anchor 설치도 동일한 선택 npm과 engine-strict를 사용한다. local lint와 CI 모두 warning0이다. Doctor의 기존 full/blocking warning과 doctor:audit 옵션은 그대로다. .nvmrc만 수정해도 기존 frontend workflow를 실행하도록 path에 selector를 포함했다.

frontend Dockerfile은 기존 Debian slim 계열을 Node22.23.1-bookworm-slim 및 검증된 multiarch index digest로 고정한다. 기존 22-slim alias의 관측된 bookworm 관계와 exact patch index의 SHA256을 공식 registry metadata로 확인했다. 이는 live 이미지 재관측이나 layer pull/build 증거가 아니다. anchor .npmrc를 설치 전에 COPY하고 실제 npm12 선택 뒤 strict ci한다. 다단계 builder가 webpack 산출물을 만들고 최종 runner는 USER node로 실행한다. 이전 Dockerfile의 dev CMD는 production start로 정리하되 Manager의 기존 build→start override·포트·앱 코드·backend/DB/RustFS lifecycle은 유지한다. full Next/node_modules·소스·설정·vendor를 보존하므로 standalone 전환이나 runtime pruning은 하지 않는다. .next와 Next 생성 설정의 소유권만 이미지 안에서 맞추며 호스트 chmod·Root ENV 변경은 하지 않는다. 실제 이미지 UID/읽기·쓰기/native ABI/normal start/auth/proxy/worker 수용 전에는 Docker profile을 검증 완료로 부르지 않는다.

개발용으로 선택 Node runtime을 준비한 뒤 각 anchor에서 다음을 사용한다.

~~~bash
# frontend 또는 tests 디렉터리에서; 선택 Node22.23.1 shell
npm install --global "$(node -p 'require("./package.json").packageManager')"
npm ci --engine-strict
~~~

운영 global Node/npm을 갱신하는 지시가 아니다. N150는 별도 private pinned runtime을 준비하고 source별 격리 stage로 검증한다. Common PR51의 실제 병합 36e4d285ea926b9d8c20da4221ade86ebf74c04d를 uses/common-ref에 같이 고정한다. 추가 toolchain-manifests는 명시 JSON ["tests/package.json"], node-dockerfiles는 ["frontend/Dockerfile"]이다. frontend workflow의 PR/push paths에 중앙 policy workflow를 포함해 policy 연결만 바뀌어도 정확한 최종 source의 기능 검사를 실행한다.

## C11 수용과 지도 문서의 범위

현재 지도 구현은 frontend/src/components/VWorldMap.tsx에서 GitHub 고정 vworld-map-web의 VWorldMapView/Marker/Popup을 동적 import한다. 직접 WMTS 구성이었다는 과거 ADR/일지/이관 보고서는 역사로 보존하고 현재 안내만 wrapper 구현과 맞춘다.

f2db107cc4bfb58115b890ea6198a2fe0c321e17 배포·로그인/공통 표·Pretendard·지도·모바일/로그아웃 수용은 [Common 최종 수용 영수증](https://github.com/digitie/kor-travel-common/blob/678a5bcf0150ac0386bfa86106e7e0f4f77e8639/docs/reviews/adversarial/evidence/2026-11-12-frontend-deployment-receipt.json)에 연결한다. 이번 Node/npm/Docker metadata 변경의 새 이미지·운영 수용을 그때 결과로 대신하지 않는다. C11의 같은 버전 bytes를 재pack하지 않는다.

## 검증 계획

지금은 두 lock의 root 엔진 외 전체 graph/버전/override·vendor/원장·앱 소스·역사 보존, CI step 상대순서와 기존 flag 보존, Docker base index SHA/아키텍처 metadata, JSON·diff를 가볍게 확인한다. WSL 의존성 설치와 전체 빌드는 하지 않는다.

정확한 private Node22.23.1/npm12.0.1과 부모 슬롯에서 fresh strict ci/공통 guard/lint/type/unit/Doctor/build/기존 common UI 브라우저10을 source-bound stage로 검증해야 한다. Docker 실제 build도 별도 슬롯에서 진행한다. 기존 결과를 이번 source의 PASS로 재사용하지 않는다. CI order/needs/fail-fast 감사/최적화는 계속 마지막 단계이며 이번에 다루지 않는다.

## Archive 테스트 하니스와 후보2 증거

공통 UI 하니스의 상태 경로는 repo .git/common-ui-session이며 부모는 tests/.tmp가 아니다. git archive에는 .git이 없어서 후보2 첫 실행이 로그인503/10실패였고, 소유 archive에 부모를 준비한 뒤 단일1/전체10이 통과했다. 정상 GitHub checkout에는 .git이 있으므로 이를 fresh CI 결함으로 일반화했던 주장은 철회했다. 기존 실패·0개 선택 오류 원문은 보존한다.

후보3의 테스트 helper는 같은 경로의 부모만 스스로 준비한다. 인증값·production 계정·assertion·timeout·retry를 바꾸지 않는다. 31997b9 source의 수동 부모 준비 없는 fresh archive에서 원래10개가 첫 실행 10PASS(52.1초)였다. 초기 .git ABSENT와 helper 생성 뒤 UID1000/state0700/nonce0600, 소스577파일 불변·프로세스/포트 정리를 확인했다. 후보2의 수동 준비 후10PASS와 별도 증거다. 후보2의 native unit396/Doctor0/build는 앱 소스·의존성 불변 bridge로만 연결하며 새 Docker 이미지 결과와 구분한다.


## 공개 build 입력과 기존 공식 재빌드 경로

현재 frontend source의 NEXT_PUBLIC 입력은 NEXT_PUBLIC_API_BASE_URL과 NEXT_PUBLIC_VWORLD_SERVICE_KEY 두 개다. Docker builder에 이 둘만 ARG/ENV로 전달하고 own Compose의 frontend build.args에 동일한 두 공개 변수만 연결한다. .env/.env.*는 계속 build context에서 제외하며 BACKEND_API_KEY, 관리자 password hash/session/proxy secret 등 server-only 값은 build ARG에 넣지 않는다.

Next의 client 공개 값은 production build에 고정된다. 이미 생성된 .next를 next start할 때 runtime ENV만 바꿔도 client 번들은 바뀌지 않는다. own Compose에서 공개 값을 변경하면 해당 공개 build 입력으로 이미지를 다시 빌드해야 한다. APP_ENV_FILE로 별도 파일을 쓰는 개발 경로는 기존 안내대로 --env-file의 보간 소스도 같은 파일로 맞춰야 한다. 기존 runtime env_file·server 인증값은 유지한다.

Manager 정본은 이미 빌드된 이미지를 --no-build로 공식 재생성한 뒤, 컨테이너의 기존 command에서 npm run build→npm run start를 실행한다. 이때 기존 두 공개 runtime ENV가 client 재컴파일 입력이 된다. 이 정상 cold rebuild에 필요한 tokens.css는 globals.css의 상대 import 그대로 runner에 포함한다. full Next/node_modules·src·설정과 USER node 및 이미지 안 writable cache/생성 파일이라는 결정도 유지한다. 새 SDK API나 옵션을 발명하거나 start-only로 바꿔 누락을 숨기지 않는다.

원 A의 tokens.css 누락과 원 B의 runtime-only 공개 입력은 최소 CSS resolver/Next static mapping 진단으로 old RED/new GREEN을 확인했다. 이 작은 진단은 기존 설치 모듈·로컬 Node22.22.2를 읽기 전용으로 사용했으며 canonical runtime/full bundle/image 수용을 뜻하지 않는다. 새 exact source의 원2 closure·정확 CI와 실제 nonroot image의 cold build→start/서로 다른 공개 build 값/client map 분기/server secret 비노출 검증은 남아 있다. 기존31997 cloud396/checkout10 및 별도 fresh archive10 원문은 그대로다.
