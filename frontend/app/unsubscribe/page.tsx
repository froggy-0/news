import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "구독 해지 안내",
  description: "구독 해지 기능은 현재 1차 구현 범위에서 제외되어 있습니다.",
};

export default function UnsubscribePage() {
  return (
    <main className="space-y-6">
      <section className="panel panel-soft">
        <p className="section-label">unsubscribe</p>
        <h1 className="section-title">구독 해지 안내</h1>
        <div className="copy-block">
          <p>구독 해지 기능은 현재 1차 공개 프론트 범위에 포함되어 있지 않습니다.</p>
          <p>
            향후 메일 구독 기능이 추가되면, 이 경로에서 해지 절차를 제공하고 관련 정책도 함께
            안내할 예정입니다.
          </p>
        </div>
      </section>
    </main>
  );
}
