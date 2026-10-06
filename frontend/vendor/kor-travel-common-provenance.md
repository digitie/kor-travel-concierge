# 공통 UI 배포물 출처

공통 저장소의 GPL-3.0-or-later UI/tokens 배포물을 Map이 검증한 동일 tarball로 채택한다.
정본: `kor-travel-common`의 `efcd671207d7f9e2fb01251bab6854a8d543279a`.
`@kor-travel/ui`는 `0.1.0-dev.6`, tokens는 `0.1.0`이다. tarball에 LICENSE·NOTICE·
THIRD_PARTY_NOTICES와 실제 dist가 포함된다. npm lockfile의 integrity와 Docker의
vendor COPY→npm ci를 함께 보존한다. 인증·세션·BFF actor는 Concierge가 소유한다.
