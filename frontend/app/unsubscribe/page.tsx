import type { Metadata } from "next";
import { Suspense } from "react";

import { UnsubscribeResult } from "@/components/layout/UnsubscribeResult";

export const metadata: Metadata = {
  title: "구독 해지",
  description: "SOVEREIGN BRIEF 메일 구독 해지 페이지입니다.",
};

export default function UnsubscribePage() {
  return (
    <main className="space-y-6">
      <Suspense fallback={null}>
        <UnsubscribeResult />
      </Suspense>
    </main>
  );
}
