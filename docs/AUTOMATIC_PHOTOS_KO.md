# 자동 사진 획득과 비공개 카드뉴스 미리보기

`AUTO_PHOTO_ACQUIRE=1`이면 기획 승인 후 render 작업이 주제 사진을 자동 확보한다. 기존 수동 사진 등록·라이브러리 재사용은 계속 지원한다. DB 스키마 변경은 없다.

1. 기획안의 `image_queries`와 장면을 사용해 본문/중간 결의용 검색어를 나눈다. 각 장면은 최초 검색과 대체 검색 최대 2회로 제한한다.
2. 기존 Pixabay 검색을 재사용한다. 키가 원본/fullHD URL을 제공할 때만 자동 획득에 사용한다. 기본 키의 최대 1280px 이미지는 1080×1350 무업스케일 크롭 조건을 충족하지 못하므로 확대하거나 원본 URL을 추측하지 않는다.
3. 고해상도 URL이 없으면 Wikimedia Commons API에서 CC0가 명시된 파일만 검색한다. CC BY/CC BY-SA, 출처 불명, 제약이 표시된 파일은 자동 선택하지 않는다. 반환된 URL만 사용한다. 검색 응답은 24시간 캐시한다.
4. 시도마다 상위 후보 최대 2개에 기존 다운로드·실제 바이트 검사를 적용한다. JPEG/PNG/WebP, 크기/픽셀/선명도, 4:5 크롭의 원본 해상도, SHA-256 및 지각 해시 중복을 검사한다.
5. Claude 시각 검사에서 사진성·주제 적합성·워터마크 없음·AI 징후 없음·인물 없음·로고 없음·적절성이 모두 true이고 확신도 0.9 이상인 경우만 비공개 미리보기에 사용한다. 불확실하거나 알려진 AI/워터마크 태그는 제외한다. 기계 검사가 AI 여부나 권리를 보증하는 것은 아니다.
6. 자동 선택은 `human_reviewed=false`, `review_required=true`, `final_human_review_required=true`로 기록한다. 사람 검토 완료 필드를 생성하지 않는다. 출처·라이선스 근거·검사 방법·모델·시각·원본 해시를 image_inputs 및 assets에 보존한다.
7. 기존 Figma 렌더러로 생성하고 Telegram 앨범 전달 성공 후 최종 승인/이미지 수정 버튼을 보낸다. 출처·검사 구분을 사용자에게 제시한다. 사진 자동 선택은 최종 승인을 대신하지 않는다.
8. 검색이 소진되면 후보 출처와 이미지 수정/검색어 변경 버튼으로 선택을 요청한다. `draft_ready`에서 이미지 수정이 가능하며 원고 본문을 보존한 새 버전으로 렌더한다.

검색·다운로드·시각 검사는 영속 체크포인트를 사용한다. 성공한 결과는 작업 재개 때 재사용한다. 시각 검사 응답이 불확실하면 자동 유료 재호출하지 않는다. 기존 일일 Claude 횟수·토큰 예약 상한도 적용된다. API 검색은 슬롯별 3개 검색어, 다운로드/시각 검사는 검색어별 최대 2개 후보로 제한된다. 후보가 충분하지 않으면 작업은 대기한다.

기존 작업 재개는 원고·승인·이미지 버전을 확인한 뒤 `bureau.cli resume 4`와 같은 명시적 재개를 사용한다. running/uncertain 체크포인트가 있으면 강제 초기화하지 않는다. 다른 버전이 승인되었거나 결과가 변경되면 재개하지 않는다.

현재 허용 범위는 비공개 렌더링과 Telegram 전달이다. `ENABLE_PUBLIC_MEDIA=0`, `INSTAGRAM_PUBLISH_ENABLED=0`을 유지한다. 원고/이미지 수정은 승인·게시된 버전을 변경하지 않는다.

라이선스 정책은 2026-10-30 공식 문서와 대조했다. 기계 판정은 개별 업로더의 권리 보증을 대신하지 않으며 추가 권리 가능성을 기록한다. 정책 확인일이 30일을 넘으면 재검증 전 자동 선택을 차단한다.

- Pixabay API: https://pixabay.com/api/docs/
- Pixabay Content License: https://pixabay.com/service/license-summary/
- Commons 재사용 안내: https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia
- CC0: https://creativecommons.org/publicdomain/zero/1.0/

오프라인 검증: 전체 109개 테스트 통과. 자동 선정 근거·허위 사람 검토 방지·불명 라이선스 거부·저해상도/변조/중복 거부·검사 실패 차단·검색 상한·캐시·기존 waiting 렌더 재개·실패 시 사용자 선택 요청을 포함한다.

## 첫 운영 검증에서 보강한 항목

Commons API가 반환하는 thumb.wikimedia.org도 공식 다운로드 호스트로 허용한다. upload.wikimedia.org와 함께 정확한 반환 URL만 사용하며 임의 크기 URL을 만들지 않는다. 다운로드 HTTP 429는 Retry-After(없으면 900초)를 보존하고 추가 다운로드를 즉시 차단한다. 반복적인 출처 요청이나 속도 제한 우회는 하지 않는다.
