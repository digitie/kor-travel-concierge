# 공통 UI·지도·CSS 후보 배포물 출처

2026-11-12 현재 정본은 integration-9-review다. 부모가 제공한 파일을 그대로 소비하며 독립 repack은 하지 않았다.
CANDIDATE_NOT_RELEASED이며 최종 릴리스·운영 적용 완료가 아니다. 정본은 frontend/common-artifacts.json과
부모 artifacts/integration-9-review/common-artifacts.json이다.

- 공통 source 및 중앙 reusable code pin: 2c1182e765bb2bc53e01e0962cf2a73683891e1d
- 지도 source: 9a7a348b02d61969b394c681b024d5851eef836b
- Lightning CSS nativecss.fix.4 source: 748651cbd845971e65c411166ddee101745dab21
- serde-content source: 18e53fcf6f8ace093a292891b34fa3411192617d
- 부모 확인 기준 VWorld PR32와 serde-content PR1은 병합됐고, 원장의 source와 tree가 같다.
  이 소비자에서 tarball을 교체하거나 재pack하지 않았다.

| 사용 패키지 | 버전 | 배포물 라이선스 필드 | SHA512 |
| --- | --- | --- | --- |
| @kor-travel/ui | 0.2.0 | GPL-3.0-or-later | sha512-buhlDym3/Id355Cse+lwBsFk3G1nz3dY2XviAA+X82TZPXmcujYGxItRZafsY0t4xsWkiQ3jAxtCYjFZ7JsbEQ== |
| @kor-travel/tokens | 0.1.1 | GPL-3.0-or-later | sha512-+JglXOZhP11afRr/upKHWz7cjsj4IPIKYkoVh8lq9IcJTKU8zIHA8pirC1IOS1++gqOmMCnPkj1oi8EzJsTUyQ== |
| lightningcss | 1.33.0+nativecss.fix.4 | MPL-2.0 | sha512-zDQ03VJE37OlyBrLsRcsEdIVu0T4BXJKDH5y9//To6GlGN2UrKQGERFVAFblkPQ5ZEbhuOp5wpXxGARZNdbQLA== |
| vworld-map-core | 1.0.1 | GPL-3.0-only | sha512-Djm14Arr7U0r7Sabj6P0V57CdzWIGaJmecklmY1hwrq1QUZJjMUFgkZfGRFalUo6AFzHEwwzOEzbJPMifGhINw== |
| vworld-map-web | 1.0.3 | GPL-3.0-only | sha512-HPXZcz/wP6tFsCZqlAbansWNICcZPubC+/V7rDWXYTQVlOBLl9cZQ1HSMJd25c2CZoMNreVFTQA0vzkVglkS1w== |

C8→C9에서 UI94파일/tokens25파일 중 각각 check-dependencies.mjs 한 파일만 바뀌었다.
런타임·CSS·metadata117파일은 byte 동일하며, 현재 node_modules의 사용 배포물248파일도 archive 원문과 일치한다.
원장의 RN 패키지는 이 앱이 소비하지 않는다. core1.0.0 및 오래된 UI/tokens vendor는 이미 제거했다.

라이선스·NOTICE·THIRD_PARTY_NOTICES 및 shadcn 제3자 고지는 원문 그대로 보존한다.
source SPDX 및 라이선스의 P0 보완, CSSfix4, VWorld 공개 mapStyle은 부모 배포물을 그대로 사용한다.
키 없는 지도는 빈 sources의 mapStyle로 마커·팝업을 렌더하며 더미 키·외부 타일 요청을 만들지 않는다.

서명된 정식 릴리스로 간주하지 않으며 최종 freeze·common foundation merge·소비자 독립2리뷰·정확 HEAD CI·
부모 go는 별도 gate다. DB/RustFS/API/Dagster 수명주기와 운영 secret은 변경하지 않았다.
