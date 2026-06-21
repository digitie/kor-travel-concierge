"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateSourceTarget, type SourceTargetSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const INTERVAL_OPTIONS = [
  { value: 60, label: "1시간" },
  { value: 720, label: "12시간" },
  { value: 1440, label: "1일" },
  { value: 10080, label: "1주일" },
  { value: 20160, label: "2주일" },
  { value: 43200, label: "1달" },
  { value: 129600, label: "3달" },
];

function intervalLabel(value: number): string {
  return (
    INTERVAL_OPTIONS.find((option) => option.value === value)?.label ??
    `${value}분`
  );
}

export function RecurringEditDialog({
  target,
  onClose,
}: {
  target: SourceTargetSummary | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const open = Boolean(target);
  const [intervalEdit, setIntervalEdit] = useState<number | null>(null);
  const [maxRunsEdit, setMaxRunsEdit] = useState<number | null>(null);

  const interval = intervalEdit ?? target?.scan_interval_minutes ?? 1440;
  const maxRuns = maxRunsEdit ?? target?.max_runs ?? 0;

  function close() {
    setIntervalEdit(null);
    setMaxRunsEdit(null);
    onClose();
  }

  const mutation = useMutation({
    mutationFn: () =>
      updateSourceTarget(target!.id, {
        scanIntervalMinutes: interval,
        maxRuns,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["source-targets"] });
      close();
    },
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>반복 작업 수정</DialogTitle>
          <DialogDescription>
            {target?.display_name ?? target?.source_value}
          </DialogDescription>
        </DialogHeader>

        <Field>
          <FieldLabel htmlFor="recurring-edit-interval">반복 간격</FieldLabel>
          <Select
            value={String(interval)}
            onValueChange={(value) => setIntervalEdit(Number(value))}
          >
            <SelectTrigger id="recurring-edit-interval" className="w-full">
              <SelectValue>{intervalLabel(interval)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {INTERVAL_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={String(option.value)}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>

        <Field>
          <FieldLabel htmlFor="recurring-edit-count">반복 횟수</FieldLabel>
          <Input
            id="recurring-edit-count"
            type="number"
            min={0}
            value={String(maxRuns)}
            onChange={(event) =>
              setMaxRunsEdit(Math.max(0, Number(event.target.value) || 0))
            }
          />
          <FieldDescription>
            0이면 무한. 현재 {target?.run_count ?? 0}회 실행됨.
          </FieldDescription>
        </Field>

        {mutation.error ? (
          <p className="text-xs text-destructive">{mutation.error.message}</p>
        ) : null}

        <DialogFooter>
          <DialogClose
            render={
              <Button type="button" variant="outline">
                닫기
              </Button>
            }
          />
          <Button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            저장
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
