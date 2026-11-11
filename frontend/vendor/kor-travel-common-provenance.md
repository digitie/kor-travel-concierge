# 공통 UI·지도 후보 배포물 출처

2026-11-11 부모의 통합 검증 후보 3을 동일 bytes로 소비한다. 상태는 CANDIDATE_NOT_RELEASED이며 정식 릴리스나 최종 freeze가 아니다.

공통 소스의 인계 기준은 kor-travel-common@c289b4624c8640eb918cc915803e72ae754e58fb이고 추가 변경은 부모 통합 커밋 원장에서 확정한다. 지도 기준은 digitie/maplibre-vworld-react@9c46c57181d433c91f7e8837c4e4396204e9b583이며 부모의 web tsconfig 보완을 포함한다. web1.0.3/core1.0.0을 직접 file 의존성으로 고정한다.

| 패키지 | 버전 | SHA512 |
| --- | --- | --- |
| @kor-travel/ui | 0.2.0 | sha512-ZugCh1iLt2GjU2TcoqWondPHMNb2PA0dA4/CAK23/yTZhMfPyI4kKmHnrt3xbkNiydEKUATPSF20pH10OeHCHw== |
| vworld-map-core | 1.0.0 | sha512-tP++7XNg9UYXeeUc+aX8q+RD6/dkVzZuBSXPHUKEqHIRobLjUo1HcPEJruOU0bUzHGxnJL/8reIM7xI+vXYaUw== |
| @kor-travel/tokens | 0.1.1 | sha512-LJpKb3co9PGl997zBG98u8aZF3jwPHuunDbg5hVu+inMZHbmG1rMoS9Alpxce/ErAUZyTbaZmh6eS6LVT9jfHw== |
| vworld-map-web | 1.0.3 | sha512-9S0TUlgu4ky9ztjkanf0lhoijydhcX5ehHtyQB1jla+rGnuPLK4POiH4wIb2v5ATKuO5hOnHEG534gfyuEH+5g== |

정본은 frontend/common-artifacts.json이다. tarball의 LICENSE·NOTICE·THIRD_PARTY_NOTICES와 shadcn MIT 출처 고지를 보존하며, 실제 파일·원장·lock integrity를 npm run check:dependencies로 검증한다. 최종 freeze가 새 원장을 제공하면 파일 복사 뒤 명시적 file 설치와 전체 검증을 다시 수행한다. 인증·세션·BFF actor·DB·RustFS는 Concierge의 기존 경계를 따른다.
