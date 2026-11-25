# 현재 Common 터치 영역·포커스·Dialog 제목 정본(ui 0.2.6)

UI0.2.6과 tokens0.1.7은 [Common producer 05d7f91](https://github.com/digitie/kor-travel-common/commit/05d7f91a4151a69d72b8bf1dc0007291c6ab2a61)의 main CI artifact14803131043 원본이다(PR #83: VirtualTable md 미만 선택 칸 44px, AccordionContent 포커스 outline 잘림 수정, 닫기 버튼이 있는 DialogTitle의 `pr-7`·`wrap-anywhere`). 로컬 pack 재생성은 하지 않았다. [Common catalog 309b881](https://github.com/digitie/kor-travel-common/blob/309b881f8fd6d657b448f43b6fc61939fde742c2/frontend-artifacts.json)(PR #84)의 버전·파일명·SRI를 common-artifacts.json과 lock에 연결했다. artifact의 SHA256SUMS(`sha256sum -c` OK)·SRI와 내려받은 tgz의 sha512가 catalog와 같다.

- ZIP digest: `sha256:76ba4636db7cc2deeaff2ec059820981da0e4619597155eb345f70b5c93ca54a`
- UI SHA256: `14e9853ceb720b6db4a173ee3411bb07e9d3d9c445c3f8bb45719499d4036110`
- tokens SHA256: `a0422f551331e521cfdc819d1edd0bca0b90f33507a178ab2d8baea3256e8b53`
- lock은 두 tgz의 version·resolved·integrity와 ui peer(tokens 0.1.7)만 바뀐다(ui·tokens dependencies 목록 불변). 미사용 Toast 0.1.6은 설치하지 않는다. 기존 VWorld·Radix/LightningCSS 패치 bytes와 출처는 유지한다.
- 앱 로컬 정책(2026-11-25, T-211): `src/components/ui/dialog.tsx`·`alert-dialog.tsx`의 Content가 공개 prop(`onOpenAutoFocus`/`onCloseAutoFocus`)으로 trigger 없는 대화상자의 focus를 연 요소로 돌려준다(`src/lib/dialog-focus-return.ts`). 공통 bytes·focus trap은 바꾸지 않았고, Common 상류에 같은 동작이 들어오면 이 로컬 정책을 걷어낸다.

# 이전 Common 입력·선택 포커스 정본(ui 0.2.5)

UI0.2.5와 tokens0.1.6은 [Common producer fe14114](https://github.com/digitie/kor-travel-common/commit/fe141143cc8ba75e8fd0b6134e1c9e518e294fa2)의 main CI artifact14782962353 원본이다(PR #81 입력·선택 컨트롤 포커스 FS-7.8, 체크박스·스위치 md 미만 터치 영역 44px). 로컬 pack 재생성은 하지 않았다. [Common catalog ade7b3e](https://github.com/digitie/kor-travel-common/blob/ade7b3eb50c0197caad4a1c98fcb97cffbc2a8a4/frontend-artifacts.json)(PR #82)의 버전·파일명·SRI를 common-artifacts.json과 npm12 생성 lock에 연결했다.

- ZIP digest: `sha256:065bfbdfed8a81c4538371d0515f2ff23cc5b67826f8d1f42a7db1431408ab72`
- UI SHA256: `6f365a12f966d1b33d06219e003c30bf15eedf965d100543f2b2e06acf67d2f1`
- tokens SHA256: `4a3256fa17f72ef3677b9c7e9489e8b27d566a3244b3dad1b3a672333a544be5`
- 미사용 Toast는 설치하지 않는다. 기존 VWorld·Radix/LightningCSS 패치 bytes와 출처는 유지한다.

# 이전 Common 관리자 셸 정본(ui 0.2.3)

UI0.2.3와 tokens0.1.4는 [Common producer0e2a3f5](https://github.com/digitie/kor-travel-common/commit/0e2a3f5aa16323df0d009360802661c9bc496dc6)의 main CI artifact14500111373 원본이다. 로컬 pack 재생성은 하지 않았다. [catalogd644](https://github.com/digitie/kor-travel-common/blob/d644632ea9eaf2f6b6baa49305d65fae5bbc0bd4/frontend-artifacts.json)의 버전·파일명·SRI를 common-artifacts.json과 npm12 생성 lock에 연결했다.

- ZIP SHA256: `19881f2c3ed598ed7ec213c559be21ece2be77068bddee6de5bd249b6f8019e1`
- UI SHA256: `aa19793165ae37b2214d210692e23235545e1464c4e0059f99d943411fa753d9`
- tokens SHA256: `33d08d7b37c60d3e319da19608ce05137f6bf587dc8d42e3ce0dfb4b597a61fc`
- tar의 regular file에서 유도한 실제 사용 파일: UI96+tokens25=121. 미사용 Toast는 설치하지 않는다. 기존 VWorld·Radix/LightningCSS 패치 bytes와 출처는 유지한다.

다음은 이전 릴리스의 출처 이력이다. 현재 버전은 위 원장과 lock을 따른다.

# 공통 산출물 채택 출처

고정 catalog/policy C는 main 병합 P(2b0c02a2018c2c8c791bc6d6c7b5a2290579e09e)의 선행 commit이다. 실제 R/P pack bytes 동일성이 확인됐다. 운영 적용은 별도다.

pack 생성 SOURCE_SHA: 706aaa7821588dfca72f660c9161f56be2d0445f
고정 catalog commit: 5c1b3857e9af060d30ec776157760fb9e9c13ded
정책 commit: 5c1b3857e9af060d30ec776157760fb9e9c13ded
main 발행 근거: https://github.com/digitie/kor-travel-common/actions/runs/44313659808/artifacts/14430019630
producer: 706aaa7821588dfca72f660c9161f56be2d0445f

- @kor-travel/tokens 0.1.3 sha512-m1WsuJw1DHYxAkPsJpAIrFN5P/Udb+Ln/sZHbrmPJpItQDHx+wuf8QEFgSrBsk5yW+NAX5CQnIQZRkPIFwO97A==
- @kor-travel/ui 0.2.2 sha512-/odxLZlFlMj0IB8oPMyjE77kj1MtZO46m/lyHiCTW/gYFq7o6XUSrSPOC7rm7cyEpbjD8dAnCqcz7zmE2GWF+Q==

기존 직접 의존성만 갱신한다. Pinvi 모바일은 tokens-only를 유지한다.
lock은 Node26/npm12 재생성과 정본 guard 대조 후 수용한다.

## 과거 출처 기록 — 이전 현재 버전 설명

# 공통 UI·지도·CSS·Focus Scope 후보 출처

2026-11-17 현재 정본은 integration-12-review다(common #58 `97f8ed98` 동결: ui 0.2.1·tokens 0.1.2·vworld web 1.0.4/rn 1.0.2). 부모의 tgz·원장·sources를 그대로 소비한다.
common PR49는 main e8ed3ae75000be5cd22a3a11492bd97660635d78로 병합됐다.
동일 버전의 bytes 변경·독립 repack은 하지 않는다. 후속 runtime 변경은 새 버전으로 소비한다.
원장의 제작 시점 CANDIDATE_NOT_RELEASED 라벨은 정본 그대로 보존한다. 원장의7종 중 이 웹 앱은6종을 직접 사용하고 RN은 사용하지 않는다.

- 공통 producer: 938d1db701286414113324da714132db62e3311e (ui 0.2.1·tokens 0.1.2, common 97f8ed9 main push docs artifact `common-release-packs-97f8ed98…`와 byte 동일)
- 중앙 reusable code pin: 55a921b55d248106cbe320e7f5305f3d3cdb60fe (동일 generic checker 유지)
- Radix 원본/패치 source: 1752a539c8d5ae57961a0fa2702d2573d48fefe7
- 지도 source: 79b70997de8dd4a6bcc9630233f14f273cb27991 (web 1.0.4 — #33 `vworld://` 스킴 수정, main push CI pack. core 1.0.1은 이전 pack과 byte 동일)
- Lightning CSS fix4 source: 748651cbd845971e65c411166ddee101745dab21
- serde-content source: 18e53fcf6f8ace093a292891b34fa3411192617d

| 사용 패키지 | 정확 버전 | 배포물 라이선스 필드 | SHA512 |
| --- | --- | --- | --- |
| @kor-travel/ui | 0.2.1 | GPL-3.0-or-later | sha512-Yk0TFRE3UUPhHH3ErzgYQtNft+pzy3J5oYZaLwc4MnhUVUT3KPlvCQJDZtj8MvbKdNcVmi4fduxx3Z0FcIfTnw== |
| @kor-travel/tokens | 0.1.2 | GPL-3.0-or-later | sha512-IF5qTyPe0LrVFvHRHp2roruudcOO2U96b11zVr0D+Ir1Twsuc2UcAqkYoEL6LfMpDMiq6Xp+CfIDv7N/zkmo/w== |
| lightningcss | 1.33.0+nativecss.fix.4 | MPL-2.0 | sha512-zDQ03VJE37OlyBrLsRcsEdIVu0T4BXJKDH5y9//To6GlGN2UrKQGERFVAFblkPQ5ZEbhuOp5wpXxGARZNdbQLA== |
| vworld-map-core | 1.0.1 | GPL-3.0-only | sha512-Djm14Arr7U0r7Sabj6P0V57CdzWIGaJmecklmY1hwrq1QUZJjMUFgkZfGRFalUo6AFzHEwwzOEzbJPMifGhINw== |
| vworld-map-web | 1.0.4 | GPL-3.0-only | sha512-yuie33P42nb6pHoR+rI3OTNzXmW/HdIbh6RCEWEooaVTg2lNax8NkakTiadZR/Osw34a6IO0jRxANaE16g6mKA== |
| @radix-ui/react-focus-scope | 1.3.1+kortravel.fix.2 | MIT | sha512-v3XweXrUSZ/QfrMVvYmsAkVNDnvcN21QKbSrViXYf0OQf5Ue9xSgqQIukgGjsYMEBQ5qxQW8fnOC9t1Y0ENPXw== |

공식 package identity @radix-ui/react-focus-scope를 dependencies의 file:vendor 산출물로 직접 선언했다.
이 앱의 npm root인 frontend/package.json의 overrides는 $@radix-ui/react-focus-scope를 참조한다.
Dialog/Popover/Menu/radix-ui 모두 같은 패치 root 모듈을 사용하며 lock에 Scope 사본은1개다.
앱 소스는 공통 UI 경로를 계속 사용하며 자체 focus trap·monkeypatch는 추가하지 않았다.

C11→C12(2026-11-17): ui 0.2.1·tokens 0.1.2는 내장 dependency 정책·검사기와 package.json만 바뀌었고 컴포넌트·CSS·토큰 런타임 파일은 같다.
vworld-map-web 1.0.4는 타일 스킴 처리만 바뀌었고 공개 API는 그대로다. 아래는 C10→C11 당시 기록이다.

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
