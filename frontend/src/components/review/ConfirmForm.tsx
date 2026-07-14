"use client";

import { MapPinIcon } from "lucide-react";

import type { CategoryOption } from "@/lib/api";
import {
  isSelectedHitModified,
  type NearbyPlaceCandidate,
  type ReviewResolutionForm,
  type SelectedPlaceHit,
} from "@/lib/review-provenance";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  PLACE_SEARCH_PROVIDER_LABELS,
  type ConfirmFormNearbyConflict,
} from "@/components/review/types";

export type ConfirmFormProps = {
  form: ReviewResolutionForm;
  selectedHit: SelectedPlaceHit | null;
  categories: readonly CategoryOption[];
  latitudeInvalid: boolean;
  longitudeInvalid: boolean;
  coordinatesOutOfKorea: boolean;
  canSave: boolean;
  selectedActionable: boolean;
  candidateActionPending: boolean;
  resolutionError: string | null;
  nearbyConflict: ConfirmFormNearbyConflict | null;
  onNameChange: (value: string) => void;
  onLatitudeChange: (value: string) => void;
  onLongitudeChange: (value: string) => void;
  onCategoryChange: (code: string) => void;
  onSave: () => void;
  onIgnore: () => void;
  onDismissNearbyConflict: () => void;
  onMergeNearbyPlace: (place: NearbyPlaceCandidate) => void;
  onCreateNewNearbyPlace: () => void;
};

export function ConfirmForm({
  form,
  selectedHit,
  categories,
  latitudeInvalid,
  longitudeInvalid,
  coordinatesOutOfKorea,
  canSave,
  selectedActionable,
  candidateActionPending,
  resolutionError,
  nearbyConflict,
  onNameChange,
  onLatitudeChange,
  onLongitudeChange,
  onCategoryChange,
  onSave,
  onIgnore,
  onDismissNearbyConflict,
  onMergeNearbyPlace,
  onCreateNewNearbyPlace,
}: ConfirmFormProps) {
  return (
    <>
      <div className="flex flex-col gap-2 rounded-xl border p-3">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <MapPinIcon className="size-4 text-muted-foreground" />
          확정 정보
        </p>
        {selectedHit ? (
          <div className="flex flex-col gap-1 rounded-lg bg-muted/60 p-2 text-xs">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-medium">선택 원본</span>
              <Badge variant="outline">
                {PLACE_SEARCH_PROVIDER_LABELS[selectedHit.hit.provider]}
              </Badge>
              {isSelectedHitModified(form, selectedHit) ? (
                <Badge variant="secondary">최종 입력에서 수정됨</Badge>
              ) : null}
            </div>
            <span>{selectedHit.hit.name}</span>
            <span className="text-muted-foreground">
              {selectedHit.hit.road_address ??
                selectedHit.hit.address ??
                "주소 없음"}
            </span>
            <span className="font-mono text-muted-foreground">
              {selectedHit.hit.latitude?.toFixed(5)}, {" "}
              {selectedHit.hit.longitude?.toFixed(5)}
            </span>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            직접 입력값으로 저장하며 API 출처는 manual로 기록됩니다.
          </p>
        )}
        <Input
          aria-label="확정 장소명"
          placeholder="장소명"
          value={form.name}
          onChange={(event) => onNameChange(event.target.value)}
        />
        <div className="grid grid-cols-2 gap-2">
          <Input
            aria-label="위도"
            inputMode="decimal"
            placeholder="위도"
            aria-invalid={latitudeInvalid}
            value={form.latitude}
            onChange={(event) => onLatitudeChange(event.target.value)}
          />
          <Input
            aria-label="경도"
            inputMode="decimal"
            placeholder="경도"
            aria-invalid={longitudeInvalid}
            value={form.longitude}
            onChange={(event) => onLongitudeChange(event.target.value)}
          />
        </div>
        {latitudeInvalid || longitudeInvalid ? (
          <p className="text-xs text-destructive" role="alert">
            위도·경도는 숫자로 입력하세요.
          </p>
        ) : coordinatesOutOfKorea ? (
          <p className="text-xs text-warning">
            대한민국 범위를 벗어난 좌표입니다. 저장은 가능하지만 다시 확인하세요.
          </p>
        ) : null}
        <Select
          value={form.categoryCode}
          onValueChange={(value) => onCategoryChange(value ?? "")}
        >
          <SelectTrigger className="w-full" aria-label="카테고리">
            <SelectValue placeholder="카테고리 선택(강제)">
              {form.category}
            </SelectValue>
          </SelectTrigger>
          <SelectContent className="max-h-72">
            <SelectGroup>
              {categories.map((option) => (
                <SelectItem key={option.code} value={option.code}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <div className="grid grid-cols-2 gap-2">
          <Button
            type="button"
            disabled={!canSave || candidateActionPending}
            onClick={onSave}
          >
            저장
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!selectedActionable || candidateActionPending}
            onClick={onIgnore}
          >
            제외
          </Button>
        </div>
        {resolutionError ? (
          <p className="text-xs text-destructive">{resolutionError}</p>
        ) : null}
      </div>

      <AlertDialog
        open={nearbyConflict != null}
        onOpenChange={(open) => {
          if (!open) onDismissNearbyConflict();
        }}
      >
        <AlertDialogContent className="max-w-lg">
          <AlertDialogHeader>
            <AlertDialogTitle>가까운 기존 장소를 확인하세요</AlertDialogTitle>
            <AlertDialogDescription>
              좌표가 100m 이내인 장소가 있습니다. 기존 장소에 합칠지 별도 장소로
              만들지 선택하세요.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div
            className="rounded-lg border bg-muted/40 px-3 py-2"
            aria-label="근접 중복 확인 대상"
          >
            <p className="text-xs text-muted-foreground">확정하려는 장소</p>
            <p className="font-medium">
              {nearbyConflict?.placeName || "이름 없음"}
            </p>
          </div>
          <div className="flex max-h-72 flex-col gap-2 overflow-y-auto">
            {(nearbyConflict?.places ?? []).map((place) => (
              <div
                key={place.placeId}
                className="flex items-start justify-between gap-3 rounded-lg border p-3"
              >
                <div className="min-w-0 text-xs">
                  <p className="font-medium">{place.name}</p>
                  <p className="truncate text-muted-foreground">
                    {place.roadAddress ?? place.officialAddress ?? "주소 없음"}
                  </p>
                  <p className="text-muted-foreground">
                    {place.distanceMeters.toFixed(1)}m
                    {place.nameCompatible === true
                      ? " · 이름 일치"
                      : place.nameCompatible === false
                        ? " · 이름 불일치"
                        : " · 이름 비교 불가"}
                    {place.providerIdMatch === true
                      ? " · provider ID 일치"
                      : place.providerIdMatch === false
                        ? " · provider ID 불일치"
                        : " · provider ID 비교 불가"}
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`${place.name} 기존 장소에 합치기`}
                  disabled={candidateActionPending}
                  onClick={() => {
                    onMergeNearbyPlace(place);
                    onDismissNearbyConflict();
                  }}
                >
                  기존 장소에 합치기
                </Button>
              </div>
            ))}
          </div>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button type="button" variant="outline" size="sm">
                  취소
                </Button>
              }
            />
            <Button
              type="button"
              size="sm"
              disabled={candidateActionPending}
              onClick={() => {
                onCreateNewNearbyPlace();
                onDismissNearbyConflict();
              }}
            >
              새 장소로 만들기
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
