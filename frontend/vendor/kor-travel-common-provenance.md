# 공통 UI 배포물 출처

공통 저장소의 GPL-3.0-or-later UI/tokens 배포물을 정규 `npm pack` 산출물과 같은 bytes로 채택한다.
정본: `kor-travel-common`의 `c289b4624c8640eb918cc915803e72ae754e58fb`(UI 패키지 소스는 PR47 병합
`aa232ad5f255233184de80eceaab2e9b6ccb00c9`와 같다). `@kor-travel/ui`는 `0.1.0-dev.9`, tokens는 `0.1.0`이다.
UI tarball은 정본에서 공통 CI와 같은 Node 22.23.1/npm 11.19.1로 `npm ci` 뒤 `npm pack -w packages/ui`로
재현했고, 공통 저장소가 기록한 27파일·SHA256 `b738d8824e36eb6e58d8cc6b78af7dc31233b6763248d634286044def795b403`과
일치한다. tokens tarball(SHA256 `554ae3f6a18cbf453130b29f8a2d737ddb880101b55e14535cf8d63174b47505`)은 이전 채택본
그대로다(정본 사이 tokens 패키지 변경 없음). tarball에 LICENSE·NOTICE·THIRD_PARTY_NOTICES와 실제 dist가 포함된다.
npm lockfile의 integrity와 Docker의 vendor COPY→npm ci를 함께 보존한다. 인증·세션·BFF actor는 Concierge가 소유한다.
