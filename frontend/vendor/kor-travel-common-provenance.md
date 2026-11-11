# 공통 UI·지도·CSS·Focus Scope 후보 출처

2026-11-12 현재 정본은 integration-11-review의 foundation 최초릴리스다. 부모의 단일7팩과 원장·sources를 그대로 소비한다.
common PR49는 main e8ed3ae75000be5cd22a3a11492bd97660635d78로 병합됐다.
동일 버전의 bytes 변경·독립 repack은 하지 않는다. 후속 runtime 변경은 새 버전으로 소비한다.
원장의 제작 시점 CANDIDATE_NOT_RELEASED 라벨은 정본 그대로 보존한다. 원장의7종 중 이 웹 앱은6종을 직접 사용하고 RN은 사용하지 않는다.

- 공통 producer: a35481349d6747b4f13b958ae64d9c0bbd0b5413
- 중앙 reusable code pin: 55a921b55d248106cbe320e7f5305f3d3cdb60fe (동일 generic checker 유지)
- Radix 원본/패치 source: 1752a539c8d5ae57961a0fa2702d2573d48fefe7
- 지도 source: 9a7a348b02d61969b394c681b024d5851eef836b
- Lightning CSS fix4 source: 748651cbd845971e65c411166ddee101745dab21
- serde-content source: 18e53fcf6f8ace093a292891b34fa3411192617d

| 사용 패키지 | 정확 버전 | 배포물 라이선스 필드 | SHA512 |
| --- | --- | --- | --- |
| @kor-travel/ui | 0.2.0 | GPL-3.0-or-later | sha512-BsRRdnJUp6FQ2KWkXtINb7IkrxxwnWFlLP/oVlNN4UXBKren7uTlnYT4iJsdaO98iA4Tn2EMPX06eT2uB5jEDA== |
| @kor-travel/tokens | 0.1.1 | GPL-3.0-or-later | sha512-85mqNJXqhTlA4RbtKUhmzx6rH6mOOeNmsXTJtCetQ5y8njLy+5XLZbdT6j1tf3ME9XQA6X63Ah4kmuLdqEZHbA== |
| lightningcss | 1.33.0+nativecss.fix.4 | MPL-2.0 | sha512-zDQ03VJE37OlyBrLsRcsEdIVu0T4BXJKDH5y9//To6GlGN2UrKQGERFVAFblkPQ5ZEbhuOp5wpXxGARZNdbQLA== |
| vworld-map-core | 1.0.1 | GPL-3.0-only | sha512-Djm14Arr7U0r7Sabj6P0V57CdzWIGaJmecklmY1hwrq1QUZJjMUFgkZfGRFalUo6AFzHEwwzOEzbJPMifGhINw== |
| vworld-map-web | 1.0.3 | GPL-3.0-only | sha512-HPXZcz/wP6tFsCZqlAbansWNICcZPubC+/V7rDWXYTQVlOBLl9cZQ1HSMJd25c2CZoMNreVFTQA0vzkVglkS1w== |
| @radix-ui/react-focus-scope | 1.3.1+kortravel.fix.2 | MIT | sha512-v3XweXrUSZ/QfrMVvYmsAkVNDnvcN21QKbSrViXYf0OQf5Ue9xSgqQIukgGjsYMEBQ5qxQW8fnOC9t1Y0ENPXw== |

공식 package identity @radix-ui/react-focus-scope를 dependencies의 file:vendor 산출물로 직접 선언했다.
이 앱의 npm root인 frontend/package.json의 overrides는 $@radix-ui/react-focus-scope를 참조한다.
Dialog/Popover/Menu/radix-ui 모두 같은 패치 root 모듈을 사용하며 lock에 Scope 사본은1개다.
앱 소스는 공통 UI 경로를 계속 사용하며 자체 focus trap·monkeypatch는 추가하지 않았다.

UI94+tokens25파일 중 C10→C11 dependency-policy.json2파일만 바뀌고 나머지117파일은 byte 동일하다.
그러나 Focus Scope runtime은 실제 변경이므로 이전 browser/기존 소스 리뷰로 C11 수용을 갈음하지 않는다.
같은 파일명의 UI/tokens는 inactive 설치 폴더를 회수하고 명시적 file 설치했으며,
실제 node_modules의 UI/tokens119파일과 Scope15파일을 archive 원문과 모두 비교했다.
사용6종263파일·선언·lock·SRI·canonical 원장을 함께 검증했다.

원본 라이선스·NOTICE·THIRD_PARTY_NOTICES와 SPDX·shadcn 제3자 고지를 그대로 보존한다.
Scope fix.2는 초기 panel 역방향 Tab 및 disabled fieldset/첫 legend의 실제 native 후보 선별을 수정한
33,511bytes·SHA256 1ca04870692565c243130d99c3dba91f3ac853ab2ec9538fc7b658b17fb7b49a다.
부모의 공식 패치 산출물만 사용하고 동명 다른 bytes를 독립 생성하지 않는다.
CSSfix4·VWorld3와 기존 backend·DB/RustFS/API/Dagster 수명주기·운영 secret은 변경하지 않았다.
