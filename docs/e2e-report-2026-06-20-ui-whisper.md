# UI 레벨 수집 E2E 리포트 — whisper 폴백 활성화 (2026-06-20)

T-090 UI E2E에서 `youtube-transcript-api` 차단으로 채널·키워드 소스가 0건이던 문제를,
**`faster-whisper` 오디오 전사 폴백을 활성화**해 재실행한 결과다. 함께 VWorld 지도 키도 반영했다.

## 변경

- **whisper 폴백 활성화**: `.env`/`.env.production`에 `TRANSCRIPT_WHISPER_ENABLED=true`,
  `WHISPER_MODEL_SIZE=base`. 자막이 없거나 `youtube-transcript-api`가 차단되면 yt-dlp로 오디오를
  받아 faster-whisper(CPU, int8)로 전사한다. `.env.example`에도 기본 false로 문서화.
- **VWorld 지도 키 반영**: UI 컨테이너가 `NEXT_PUBLIC_VWORLD_SERVICE_KEY`를
  `kor-travel-docker-manager`의 `NEXT_PUBLIC_VWORLD_API_KEY`에서 읽는데 미설정 상태였다.
  docker-manager `.env`에 `NEXT_PUBLIC_VWORLD_API_KEY=...`를 추가하고 UI 컨테이너만 재시작해
  지도가 정상 렌더링된다(백엔드 지오코딩 키는 이미 정상이었음).

## 결과 (깨끗한 DB, 10영상×3소스)

| 소스 | 영상 | 자막(transcript) | POI 후보 | 장소 | 지오코딩 |
| --- | ---: | --- | ---: | ---: | ---: |
| 채널 @빵이네tv | 10 | whisper | 10 | **6** | **6/6** |
| 플레이리스트 | 7 | 차단(이번 배치) | 0 | 0 | - |
| 키워드 "제주도 가족여행" | 10 | whisper | 22 | **7** | **7/7** |
| **합계** | 27 | **11/27** | 32 | **13** | **13/13** |

- 자막 확보 영상이 **3/27 → 11/27**로 늘었고, **전과 0건이던 키워드·채널 소스가 각각 7·6개 장소**를
  추출했다(전부 지오코딩). whisper가 자막 차단 환경을 우회함을 검증했다.
  - **키워드(제주)**: 제주도, 비밀의숲, 원앤온리, 호커센터, 함덕해수욕장, 안돌오름 비밀의 숲, 숙성도 함덕점.
  - **채널**: 치악산, 독립기념관, 화천박물관, 아를테마수목원, 토속어류생태체험관, 화천 산타클로스우체국.

## 한계

- **transcript 가용성 변동성**: 플레이리스트는 이번 배치에서 captions+오디오 다운로드가 모두
  YouTube rate-limit에 걸려 0건이 됐다(직전 no-whisper 실행에서는 9건이었다). whisper는 자막
  부재를 우회하지만, 오디오 다운로드(yt-dlp) 자체가 차단되면 전사도 불가하다. 하루 다회 실행으로
  누적 차단된 환경 특성이며, 시간을 두거나 프록시/쿠키로 완화할 수 있다.
- whisper `base`(CPU)는 한국어 정확도가 완벽하진 않지만, POI는 영상 설명과 결합돼 추출되므로 충분했다.

## 정리

- 실행 후 concierge 인스턴스를 운영 dev DB(`kor_travel_concierge`)로 복원, 임시 e2e DB 삭제.
- VWorld 키 반영으로 지도 렌더링 정상화는 영구 적용(docker-manager `.env`).
