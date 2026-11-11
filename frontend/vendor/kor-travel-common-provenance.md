# 공통 UI·지도·CSS·Focus Scope 후보 출처

2026-11-12 현재 정본은 integration-10-review다. 부모의 단일7팩과 원장·sources를 그대로 소비한다.
독립 repack은 하지 않았으며 CANDIDATE_NOT_RELEASED다. 원장의7종 중 이 웹 앱은6종을 직접 사용하고 RN은 사용하지 않는다.

- 공통 producer 및 중앙 reusable code pin: 55a921b55d248106cbe320e7f5305f3d3cdb60fe
- Radix 원본/패치 source: 706e27aaf87bda2df7bbb9da60cc01cebc9ff064
- 지도 source: 9a7a348b02d61969b394c681b024d5851eef836b
- Lightning CSS fix4 source: 748651cbd845971e65c411166ddee101745dab21
- serde-content source: 18e53fcf6f8ace093a292891b34fa3411192617d

| 사용 패키지 | 정확 버전 | 배포물 라이선스 필드 | SHA512 |
| --- | --- | --- | --- |
| @kor-travel/ui | 0.2.0 | GPL-3.0-or-later | sha512-avvikdgmPcgNQ8otiKOPRb/fCRSLRIEyV1dudqM4BsKfExScssK+NM7IirvH78lekd7xtEduReQ8/pyqD1BdNg== |
| @kor-travel/tokens | 0.1.1 | GPL-3.0-or-later | sha512-ope7vHGRynjiTDllGJj/qqVz6kmQ/NIsQr4+GnFmyh7jB2rdoTJI3UXU7S+CN5Z8sDMamQ1ez253+Y3ShXoqeQ== |
| lightningcss | 1.33.0+nativecss.fix.4 | MPL-2.0 | sha512-zDQ03VJE37OlyBrLsRcsEdIVu0T4BXJKDH5y9//To6GlGN2UrKQGERFVAFblkPQ5ZEbhuOp5wpXxGARZNdbQLA== |
| vworld-map-core | 1.0.1 | GPL-3.0-only | sha512-Djm14Arr7U0r7Sabj6P0V57CdzWIGaJmecklmY1hwrq1QUZJjMUFgkZfGRFalUo6AFzHEwwzOEzbJPMifGhINw== |
| vworld-map-web | 1.0.3 | GPL-3.0-only | sha512-HPXZcz/wP6tFsCZqlAbansWNICcZPubC+/V7rDWXYTQVlOBLl9cZQ1HSMJd25c2CZoMNreVFTQA0vzkVglkS1w== |
| @radix-ui/react-focus-scope | 1.3.1+kortravel.fix.1 | MIT | sha512-550B+tdvg3N/tsIzOFA8zRhoMxGnPeBRl65Wg+9kY2VEEf6TW7RZKBWckVToLNuALHYZR8J9zG8GUP7DROBflg== |

공식 package identity @radix-ui/react-focus-scope를 dependencies의 file:vendor 산출물로 직접 선언했다.
이 앱의 npm root인 frontend/package.json의 overrides는 $@radix-ui/react-focus-scope를 참조한다.
Dialog/Popover/Menu/radix-ui 모두 같은 패치 root 모듈을 사용하며 lock에 Scope 사본은1개다.
앱 소스는 공통 UI 경로를 계속 사용하며 자체 focus trap·monkeypatch는 추가하지 않았다.

UI94+tokens25파일 중 C9→C10 checker/policy4파일만 바뀌고 나머지115파일은 byte 동일하다.
그러나 Focus Scope runtime은 실제 변경이므로 C9 browser/기존 소스 리뷰로 C10 수용을 갈음하지 않는다.
같은 파일명의 UI/tokens는 inactive 설치 폴더를 회수하고 명시적 file 설치했으며,
실제 node_modules의 UI/tokens119파일과 Scope15파일을 archive 원문과 모두 비교했다.
사용6종263파일·선언·lock·SRI·canonical 원장을 함께 검증했다.

원본 라이선스·NOTICE·THIRD_PARTY_NOTICES와 SPDX·shadcn 제3자 고지를 그대로 보존한다.
Scope의 loop 수정은 부모의 공식 패치 산출물만 사용하고 동명 다른 bytes를 독립 생성하지 않는다.
CSSfix4·VWorld3와 기존 backend·DB/RustFS/API/Dagster 수명주기·운영 secret은 변경하지 않았다.
