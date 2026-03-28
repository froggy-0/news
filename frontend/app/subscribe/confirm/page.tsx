import type { Metadata } from "next";
import { Suspense } from "react";

import { SubscriptionConfirmResult } from "@/components/layout/SubscriptionConfirmResult";

export const metadata: Metadata = {
  title: "구독 확인",
  description: "SOVEREIGN BRIEF 메일 구독 확인 페이지입니다.",
};

export default function SubscribeConfirmPage() {
  return (
    <main className="space-y-6">
      <Suspense fallback={null}>
        <SubscriptionConfirmResult />
      </Suspense>
    </main>
  );
}
