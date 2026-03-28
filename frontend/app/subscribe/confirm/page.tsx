import type { Metadata } from "next";
import { Suspense } from "react";

import { SubscriptionConfirmResult } from "@/components/layout/SubscriptionConfirmResult";

export const metadata: Metadata = {
  title: "구독 확인",
  description: "SOVEREIGN BRIEF 메일 구독 확인 페이지입니다.",
};

export default function SubscribeConfirmPage() {
  return (
    <main className="px-6 py-16 md:py-24">
      <Suspense fallback={null}>
        <SubscriptionConfirmResult />
      </Suspense>
    </main>
  );
}
