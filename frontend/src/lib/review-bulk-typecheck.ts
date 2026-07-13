import type { ReviewBulkPreviewInput } from "./api";

type Assignable<Source, Target> = [Source] extends [Target] ? true : false;
type AssertTrue<Value extends true> = Value;
type AssertFalse<Value extends false> = Value;

type ValidIgnoreFilter = {
  action: "ignore";
  scope: {
    kind: "filter";
    filter: { is_domestic: false; status: "needs_review" };
  };
};

type ValidReopenFilter = {
  action: "reopen";
  scope: {
    kind: "filter";
    filter: { is_domestic: null; status: "removed" };
  };
};

type InvalidReopenFilter = {
  action: "reopen";
  scope: {
    kind: "filter";
    filter: { is_domestic: null; status: "needs_review" };
  };
};

type InvalidDeleteFilter = {
  action: "delete";
  scope: {
    kind: "filter";
    filter: { is_domestic: null; status: "removed" };
  };
};

/** `npm run type-check`가 action과 filter 상태의 정적 계약을 직접 검사한다. */
export type ReviewBulkPreviewInputTypeContract = [
  AssertTrue<Assignable<ValidIgnoreFilter, ReviewBulkPreviewInput>>,
  AssertTrue<Assignable<ValidReopenFilter, ReviewBulkPreviewInput>>,
  AssertFalse<Assignable<InvalidReopenFilter, ReviewBulkPreviewInput>>,
  AssertFalse<Assignable<InvalidDeleteFilter, ReviewBulkPreviewInput>>,
];
