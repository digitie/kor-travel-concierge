"use client";

import { useState } from "react";
import { API_BASE_URL } from "@/lib/api";

// 설정 화면: Gemini 엔진 버전 선택 후 저장 (스캐폴드).
// React Hook Form + Zod + TanStack Query mutation 전환은 T-012에서 적용한다.
export default function SettingsPage() {
  const [engine, setEngine] = useState("gemini-2.0-flash");
  const [saved, setSaved] = useState(false);

  async function handleSave() {
    try {
      await fetch(`${API_BASE_URL}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gemini_engine_version: engine }),
      });
    } catch {
      // 스캐폴드 단계: 백엔드 미가동 시에도 UI 흐름을 확인할 수 있게 한다.
    }
    setSaved(true);
  }

  return (
    <main className="mx-auto max-w-md p-6">
      <h1 className="mb-4 text-lg font-semibold">설정</h1>

      <label className="mb-2 block text-sm" htmlFor="gemini-engine-select">
        Gemini 엔진 버전
      </label>
      <select
        id="gemini-engine-select"
        value={engine}
        onChange={(e) => setEngine(e.target.value)}
        className="mb-4 w-full rounded border p-2"
      >
        <option value="gemini-2.0-flash">gemini-2.0-flash</option>
        <option value="gemini-1.5-flash">gemini-1.5-flash</option>
        <option value="gemini-1.5-pro">gemini-1.5-pro</option>
      </select>

      <button
        id="settings-save-button"
        type="button"
        onClick={handleSave}
        className="rounded bg-black px-4 py-2 text-white"
      >
        저장
      </button>

      {saved && (
        <div id="success-toast" role="status" className="mt-4 text-green-600">
          설정이 저장되었습니다.
        </div>
      )}
    </main>
  );
}
