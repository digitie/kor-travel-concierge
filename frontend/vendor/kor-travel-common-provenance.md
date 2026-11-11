# 공통 UI·지도 후보 배포물 출처

2026-11-11 설치한 integration-4 후보의 동일 bytes를 소비한다. CANDIDATE_NOT_RELEASED이며 정식 릴리스나 최종 freeze가 아니다.
다음 후보6 refresh를 요청했으며 전달 이후 lock·전체 앱 gate를 다시 검증한다.

지도 source 기준은 digitie/maplibre-vworld-react@9c46c57181d433c91f7e8837c4e4396204e9b583이며 부모의 web tsconfig 보완을 포함한다.
web1.0.3/core1.0.0을 직접 file 의존성으로 고정한다. 최종 공통·지도 source SHA는 부모의 freeze 원장으로 확정한다.

| 패키지 | 버전 | SHA512 |
| --- | --- | --- |
| @kor-travel/ui | 0.2.0 | sha512-B51TvwcAsIYou9DnEiRvdBki8qgqc1Ja6FizpM7ygsv/bLBhVJOP5nOtjybYpK0V4uNwS3bC7P/38t7A+PKVJg== |\n| vworld-map-core | 1.0.0 | sha512-tP++7XNg9UYXeeUc+aX8q+RD6/dkVzZuBSXPHUKEqHIRobLjUo1HcPEJruOU0bUzHGxnJL/8reIM7xI+vXYaUw== |\n| @kor-travel/tokens | 0.1.1 | sha512-gnlABsBfUovJe2mqw+XJwahABKSPN0Nan4BGU7fP6SXqgNpZ5Jg1rrGrxmJxwYTkizl2XtjZUMwzgppzrC4+oA== |\n| vworld-map-web | 1.0.3 | sha512-9S0TUlgu4ky9ztjkanf0lhoijydhcX5ehHtyQB1jla+rGnuPLK4POiH4wIb2v5ATKuO5hOnHEG534gfyuEH+5g== |

정본은 frontend/common-artifacts.json이다. tarball의 LICENSE·NOTICE·THIRD_PARTY_NOTICES와 shadcn MIT 출처 고지를 보존한다.
실제 파일·원장·lock integrity는 npm run check:dependencies로 검증했다.
후보 교체 시 네 파일·원장을 복사한 뒤 UI와 tokens를 명시적으로 file 설치하고 재검증한다.
인증·세션·BFF actor·DB·RustFS는 Concierge의 기존 경계를 유지한다.
