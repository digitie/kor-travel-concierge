# 공통 UI·지도 후보 배포물 출처

2026-11-11 integration-6-review의 사용 패키지 네 종과 원장을 동일 bytes로 복사했다.
CANDIDATE_NOT_RELEASED이며 정식 릴리스나 최종 freeze가 아니다.

- 공통 source: a14301c01a87d7d56e8da5bcf24c0a7f145d05a1
- 지도 source: 9a7a348b02d61969b394c681b024d5851eef836b
- 지도 최초 GitHub main 기준 9c46c57181d433c91f7e8837c4e4396204e9b583 이후 부모의 tsconfig·공개 mapStyle·라이선스 수정을 포함한다.

| 패키지 | 버전 | 배포물의 라이선스 필드 | SHA512 |
| --- | --- | --- | --- |
| @kor-travel/ui | 0.2.0 | GPL-3.0-or-later | sha512-VznXMJCxgixE5Ym3Ipnf8i3KCM+65rXcUoEwvigHavMeJv1TPmZocuL1as74x+ZP0d/5dR12gvN0jhV9fvktcQ== |
| @kor-travel/tokens | 0.1.1 | GPL-3.0-or-later | sha512-GqHyu2fwh6OKhZARTMI5aJSOom71jQhoe2Bb895sX4cG7YZ7CFzqAL1xYDv8AXlM+pBYr2A+Xy9kJAzOnnWofw== |
| vworld-map-core | 1.0.1 | GPL-3.0-only | sha512-Djm14Arr7U0r7Sabj6P0V57CdzWIGaJmecklmY1hwrq1QUZJjMUFgkZfGRFalUo6AFzHEwwzOEzbJPMifGhINw== |
| vworld-map-web | 1.0.3 | GPL-3.0-only | sha512-HPXZcz/wP6tFsCZqlAbansWNICcZPubC+/V7rDWXYTQVlOBLl9cZQ1HSMJd25c2CZoMNreVFTQA0vzkVglkS1w== |

네 파일 모두 원장 SHA512를 복사 전 검증했고 명시적 npm file 설치로 기존 캐시의 integrity를 교체했다.
UI·tokens·web처럼 파일명이 유지된 패키지도 모두 명시적으로 설치했다. core1.0.0 tarball은 제거했다.
lock의 각 설치 버전·integrity가 원장과 일치하며, 원장의 RN 항목은 이 앱이 소비하지 않는다.

원장은 frontend/common-artifacts.json이다. 각 tarball의 LICENSE·NOTICE·THIRD_PARTY_NOTICES와
그 안의 shadcn MIT 제3자 고지를 보존한다. 위 라이선스는 각 배포물 package.json의 실제 선언이다.
공통 LoginForm·CVA·표·포커스·토큰 CSS는 후보6 구현을 그대로 소비하며 앱 monkeypatch는 없다.
키 없는 지도는 공개 mapStyle에 sources가 빈 스타일을 전달해 더미 키·VWorld 타일 요청을 만들지 않는다.

strict peer 설치와 npm run check:dependencies로 파일·원장·선언·lock·소스 경계를 검증한다.
이후 중앙 policy/RC 모바일 메타데이터가 바뀌면 부모의 새 원장과 함께 변경 범위를 다시 확인한다.
인증·세션·BFF actor·DB·RustFS는 Concierge의 기존 경계를 유지한다.
