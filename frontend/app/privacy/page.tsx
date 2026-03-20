import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "개인정보 처리 안내",
  description: "SOVEREIGN BRIEF의 공개 데이터와 운영 원칙을 안내합니다.",
};

export default function PrivacyPage() {
  return (
    <main className="space-y-6">
      <section className="panel panel-soft">
        <p className="section-label">privacy</p>
        <h1 className="section-title">개인정보 처리 안내</h1>
        <div className="copy-block">
          <p>
            이 공개 브리핑 페이지는 현재 로그인이나 회원 데이터 저장 없이 운영되는 정적 페이지를
            기준으로 설계됩니다.
          </p>
          <p>
            브리핑 본문과 시장 데이터는 파이프라인이 생성한 공개 JSON 산출물을 읽어 화면에
            표시하며, 페이지 자체에서 별도의 개인별 맞춤 데이터는 수집하지 않습니다.
          </p>
          <p>
            향후 구독이나 알림 기능이 추가되면, 수집 항목과 보관 기간, 해지 절차를 별도 문서로
            분리해 안내합니다.
          </p>
        </div>
      </section>
    </main>
  );
}
