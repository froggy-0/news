"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowRight, CheckCircle2, Loader2, ShieldAlert } from "lucide-react";

import { SubscriptionState } from "@/components/ui/SubscriptionState";
import type { ConfirmSubscriptionResponse } from "@/lib/subscriptions/contracts";
import type { ConfirmSubscriptionResult } from "@/lib/subscriptions/types";

function initialState(): ConfirmSubscriptionResult {
  return {
    status: "invalid-token",
    message: "확인 링크를 확인하는 중입니다.",
  };
}

export function SubscriptionConfirmResult() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [state, setState] = useState<ConfirmSubscriptionResult>(initialState);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const response = await fetch(`/api/subscriptions/confirm?token=${encodeURIComponent(token)}`);
        const payload = (await response.json()) as ConfirmSubscriptionResponse;
        if (!cancelled) {
          setState(
            "error" in payload
              ? {
                  status: "invalid-token",
                  message: payload.error,
                }
              : payload,
          );
        }
      } catch {
        if (!cancelled) {
          setState({
            status: "invalid-token",
            message: "확인 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
          });
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const isError = state.status === "invalid-token";
  const isSuccess = !loading && !isError;

  return (
    <section className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <div className="space-y-3">
        <p className="section-title">subscription confirmation</p>
        <h1 className="section-headline max-w-3xl">
          {loading ? "구독 상태를 안전하게 확인하고 있습니다." : isSuccess ? "구독 확인이 완료되었습니다." : "구독 확인 링크를 다시 확인해 주세요."}
        </h1>
        <p className="copy-block max-w-2xl">
          {loading
            ? "확인 링크의 유효성과 구독 상태를 점검한 뒤 결과를 안내합니다."
            : isSuccess
              ? "다음 발송부터 SOVEREIGN BRIEF를 받아보실 수 있습니다."
              : "링크가 만료되었거나 이미 사용된 경우 아래 경로에서 다시 구독을 요청할 수 있습니다."}
        </p>
      </div>

      <div className="section-shell rounded-[32px] p-6 md:p-8">
        <div className="mb-6 flex items-start justify-between gap-4 border-b border-white/8 pb-6">
          <div className="flex items-start gap-4">
            <div
              className={`mt-0.5 flex h-12 w-12 items-center justify-center rounded-full border ${
                loading
                  ? "border-white/12 bg-white/[0.03] text-white/68"
                  : isSuccess
                    ? "border-[#00ff66]/25 bg-[#00ff66]/10 text-[#00ff66]"
                    : "border-[#ff6b6b]/25 bg-[#ff6b6b]/10 text-[#ff6b6b]"
              }`}
            >
              {loading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : isSuccess ? (
                <CheckCircle2 className="h-5 w-5" />
              ) : (
                <ShieldAlert className="h-5 w-5" />
              )}
            </div>
            <div className="space-y-2">
              <p className="text-[10px] font-mono uppercase tracking-[0.24em] text-white/34">
                Confirmation Status
              </p>
              <h2 className="text-xl tracking-tight text-white">
                {loading ? "확인 요청 처리 중" : isSuccess ? "구독 활성화 완료" : "확인 실패 또는 만료"}
              </h2>
            </div>
          </div>
          <span
            className={`rounded-full border px-3 py-1 text-[10px] font-mono uppercase tracking-[0.2em] ${
              loading
                ? "border-white/12 text-white/52"
                : isSuccess
                  ? "border-[#00ff66]/25 text-[#00ff66]"
                  : "border-[#ff6b6b]/25 text-[#ff6b6b]"
            }`}
          >
            {loading ? "processing" : isSuccess ? "confirmed" : "action needed"}
          </span>
        </div>

        <SubscriptionState tone={isError ? "danger" : "success"}>
          <div className="copy-block">
            <p>{state.message}</p>
          </div>
        </SubscriptionState>

        <div className="mt-6 grid gap-3 md:grid-cols-2">
          <Link
            href="/"
            className="inline-flex items-center justify-center gap-2 rounded-full border border-white/10 px-5 py-3 text-sm tracking-tight text-white/72 transition hover:border-white/24 hover:text-white"
          >
            홈으로 돌아가기
          </Link>
          <Link
            href="/archive"
            className="inline-flex items-center justify-center gap-2 rounded-full bg-white px-5 py-3 text-sm font-semibold tracking-tight text-black transition hover:bg-[#00ffff]"
          >
            브리핑 아카이브 보기
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}
