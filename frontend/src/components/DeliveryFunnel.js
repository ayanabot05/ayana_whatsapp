// src/components/DeliveryFunnel.js
import {
  FunnelChart, Funnel, LabelList, Tooltip, ResponsiveContainer,
} from "recharts";

// Ordered stage definitions. The component only plots stages that are
// actually present as keys on the `funnel` object passed in, so this same
// component works whether the caller sends a 3-stage WhatsApp delivery
// funnel (sent/delivered/read) or a 4-stage check-in funnel that also
// includes "replied".
const STAGE_DEFS = [
  { key: "sent",      label: "Sent",      color: "#8A948F" }, // ayana-muted
  { key: "delivered", label: "Delivered", color: "#3DB8E8" }, // ayana-sky
  { key: "read",      label: "Read",      color: "#0A5940" }, // ayana-primary
  { key: "replied",   label: "Replied",   color: "#25D366" }, // ayana-whatsapp
];

export function DeliveryFunnel({ funnel, testid }) {
  if (!funnel) return null;

  const stages = STAGE_DEFS
    .filter((s) => funnel[s.key] != null)
    .map((s) => ({ name: s.label, value: funnel[s.key], fill: s.color }));

  const sentTotal = stages[0]?.value || 0;

  if (stages.length === 0) return null;

  return (
    <div className="bg-white rounded-2xl border border-ayana-line p-5" data-testid={testid}>
      <h3 className="font-display text-sm font-medium text-ayana-text mb-3">Delivery funnel</h3>

      {sentTotal === 0 ? (
        <p className="text-sm text-ayana-muted">No messages sent in this period.</p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={220}>
            <FunnelChart>
              <Tooltip />
              <Funnel dataKey="value" data={stages} isAnimationActive>
                <LabelList position="right" fill="#2C2C2C" stroke="none" dataKey="name" />
              </Funnel>
            </FunnelChart>
          </ResponsiveContainer>

          <div className="flex flex-wrap gap-3 mt-3 pt-3 border-t border-ayana-line">
            {stages.map((s) => {
              const rate = sentTotal > 0 ? Math.round((s.value / sentTotal) * 100) : 0;
              return (
                <div key={s.name} className="flex items-center gap-1.5 text-xs" data-testid={`${testid}-${s.name.toLowerCase()}`}>
                  <span className="w-2 h-2 rounded-full" style={{ background: s.fill }} />
                  <span className="text-ayana-secondary">{s.name}:</span>
                  <span className="font-medium text-ayana-text">{s.value}</span>
                  <span className="text-ayana-muted">({rate}%)</span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}