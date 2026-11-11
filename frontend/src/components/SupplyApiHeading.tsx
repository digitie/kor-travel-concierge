import { HelpTip } from "@/components/HelpTip";
import type { ReactNode } from "react";

/** 공급 API 설명과 발급 경계가 같은 제목·도움말 구조를 사용한다. */
export function SupplyApiHeading({
  eyebrow,
  title,
  help,
  children,
}: {
  eyebrow: string;
  title: string;
  help: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1">
        <div>
          <p className="ktc-eyebrow mb-1">{eyebrow}</p>
          <h2 className="text-[18px] font-extrabold tracking-[-0.025em]">
            {title}
          </h2>
        </div>
        <HelpTip>{help}</HelpTip>
      </div>
      <p className="text-[13px] text-text-secondary">{children}</p>
    </div>
  );
}
