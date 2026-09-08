import { useCallback, useEffect, useState } from "react";
import {
  Users, CheckCircle2, MessageCircle, AlertTriangle, CalendarHeart,
  Loader2, Activity, ChevronLeft, ChevronRight,
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
  FunnelChart, Funnel, LabelList,
} from "recharts";
import { Navbar } from "@/components/Navbar";
import { api } from "@/lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PaginationBar } from "@/components/ui/PaginationBar";
import { DeliveryFunnel } from "@/components/DeliveryFunnel";

// ─── Constants ───────────────────────────────────────────────────────────────
const USERS_PER_PAGE = 50;
const MSGS_PER_PAGE  = 100;

const CHART_COLORS = {
  primary:   "#0A5940",
  accent:    "#FF6B35",
  gold:      "#FFC93C",
  whatsapp:  "#25D366",
  sky:       "#3DB8E8",
  coral:     "#FF5C7A",
  muted:     "#8A948F",
  danger:    "#ef4444",
};

const PIE_COLORS = [CHART_COLORS.accent, CHART_COLORS.primary, CHART_COLORS.gold, CHART_COLORS.whatsapp, CHART_COLORS.muted];

// ─── Helpers ─────────────────────────────────────────────────────────────────
function StatCard({ icon: Icon, label, value, sub, color = "primary", trend }) {
  const colorMap = {
    primary:  "text-ayana-primary bg-ayana-primary/8",
    accent:   "text-ayana-bright bg-ayana-bright/10",
    gold:     "text-[#B8860B] bg-ayana-sun/20",
    whatsapp: "text-ayana-whatsapp bg-ayana-whatsapp/10",
    sky:      "text-ayana-sky bg-ayana-sky/10",
    coral:    "text-ayana-coral bg-ayana-coral/10",
    danger:   "text-red-500 bg-red-50",
    muted:    "text-ayana-muted bg-ayana-alt",
  };
  return (
    <div className="bg-white rounded-2xl border border-ayana-line p-5 flex flex-col gap-3">
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${colorMap[color]}`}>
        <Icon className="w-5 h-5" strokeWidth={1.5} />
      </div>
      <div>
        <p className="font-display text-2xl font-semibold text-ayana-text">{value ?? "—"}</p>
        <p className="text-sm text-ayana-muted mt-0.5">{label}</p>
        {sub && <p className="text-xs text-ayana-secondary mt-1">{sub}</p>}
      </div>
    </div>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────
export default function Admin() {
  const [stats,       setStats]       = useState(null);
  const [loading,     setLoading]     = useState(true);
  const [emergencies, setEmergencies] = useState([]);
  const [deliveryHealth, setDeliveryHealth] = useState(null);

  // Paginated: users
  const [users,      setUsers]      = useState([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersSkip,  setUsersSkip]  = useState(0);

  // Paginated: messages
  const [messages,      setMessages]      = useState([]);
  const [messagesTotal, setMessagesTotal] = useState(0);
  const [messagesSkip,  setMessagesSkip]  = useState(0);

  // Paginated: schedules
  const [schedules,      setSchedules]      = useState([]);
  const [schedulesTotal, setSchedulesTotal] = useState(0);
  const [schedulesSkip,  setSchedulesSkip]  = useState(0);

  // ── Initial load ────────────────────────────────────────────────────────
  useEffect(() => {
    Promise.all([
      api.get("/admin/stats"),
      api.get(`/admin/users?skip=0&limit=${USERS_PER_PAGE}`),
      api.get(`/admin/messages?skip=0&limit=${MSGS_PER_PAGE}`),
      api.get("/admin/emergencies"),
      api.get(`/admin/schedules?skip=0&limit=${USERS_PER_PAGE}`),
      api.get("/admin/delivery-health?days=7"),
    ]).then(([s, u, m, e, sc, dh]) => {
      setStats(s.data);
      setUsers(u.data.items ?? u.data);
      setUsersTotal(u.data.total ?? (u.data.items ?? u.data).length);
      setMessages(m.data.items ?? m.data);
      setMessagesTotal(m.data.total ?? (m.data.items ?? m.data).length);
      setEmergencies(e.data);
      setSchedules(sc.data.items ?? sc.data);
      setSchedulesTotal(sc.data.total ?? (sc.data.items ?? sc.data).length);
      setDeliveryHealth(dh.data);
    }).finally(() => setLoading(false));
  }, []);

  const fetchUsers = useCallback(async (skip) => {
    const { data } = await api.get(`/admin/users?skip=${skip}&limit=${USERS_PER_PAGE}`);
    setUsers(data.items ?? data);
    setUsersTotal(data.total ?? (data.items ?? data).length);
    setUsersSkip(skip);
  }, []);

  const fetchMessages = useCallback(async (skip) => {
    const { data } = await api.get(`/admin/messages?skip=${skip}&limit=${MSGS_PER_PAGE}`);
    setMessages(data.items ?? data);
    setMessagesTotal(data.total ?? (data.items ?? data).length);
    setMessagesSkip(skip);
  }, []);

  const fetchSchedules = useCallback(async (skip) => {
    const { data } = await api.get(`/admin/schedules?skip=${skip}&limit=${USERS_PER_PAGE}`);
    setSchedules(data.items ?? data);
    setSchedulesTotal(data.total ?? (data.items ?? data).length);
    setSchedulesSkip(skip);
  }, []);

  const fetchDeliveryHealth = useCallback(async (days) => {
    const { data } = await api.get(`/admin/delivery-health?days=${days}`);
    setDeliveryHealth(data);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-ayana-bg">
        <Navbar />
        <div className="flex justify-center py-40">
          <Loader2 className="w-8 h-8 animate-spin text-ayana-primary" />
        </div>
      </div>
    );
  }

  const cards = [
    { icon: Users,         label: "Total users",          value: stats.total_users          },
    { icon: Users,         label: "New today",            value: stats.new_today ?? 0        },
    { icon: Users,         label: "New this week",        value: stats.new_7d ?? 0           },
    { icon: CheckCircle2,  label: "Completed onboarding", value: stats.completed_onboarding },
    { icon: Activity,      label: "Activated circles",    value: stats.activated            },
    { icon: CalendarHeart, label: "Paying users",         value: stats.paying_users ?? 0     },
    { icon: CalendarHeart, label: "Active schedules",     value: stats.active_schedules     },
    { icon: MessageCircle, label: "Messages sent",        value: stats.messages_delivered   },
    { icon: AlertTriangle, label: "Open emergencies",     value: stats.open_emergencies     },
  ];

  return (
    <div className="min-h-screen bg-ayana-bg">
      <Navbar />
      <main className="max-w-6xl mx-auto px-5 sm:px-8 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="font-display text-3xl font-bold text-ayana-text">Analytics Dashboard</h1>
            <p className="mt-1 text-ayana-secondary text-sm">Platform health, growth, and engagement at a glance.</p>
          </div>
          <span className={`text-xs px-3 py-1.5 rounded-full ${
            stats.whatsapp_enabled
              ? "bg-ayana-whatsapp/15 text-ayana-whatsapp"
              : "bg-ayana-accent/10 text-ayana-accent"
          }`}>
            WhatsApp: {stats.whatsapp_enabled ? "Live" : "Test mode"}
          </span>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-6" data-testid="admin-stats">
          {cards.map((c) => (
            <div key={c.label} className="bg-white rounded-xl border border-ayana-line p-5">
              <c.icon className="w-5 h-5 text-ayana-primary mb-3" strokeWidth={1.5} />
              <p className="font-display text-2xl font-semibold text-ayana-text">{c.value}</p>
              <p className="text-sm text-ayana-muted">{c.label}</p>
            </div>
          ))}
        </div>

        {stats.delivery_funnel && (
          <div className="mb-10">
            <DeliveryFunnel funnel={stats.delivery_funnel} testid="admin-delivery-funnel" />
          </div>
        )}

        <Tabs defaultValue="users">
          <TabsList className="bg-ayana-alt">
            <TabsTrigger value="users"       data-testid="admin-tab-users">Users</TabsTrigger>
            <TabsTrigger value="messages"    data-testid="admin-tab-messages">Deliveries</TabsTrigger>
            <TabsTrigger value="delivery-health" data-testid="admin-tab-delivery-health">Delivery health</TabsTrigger>
            <TabsTrigger value="schedules"   data-testid="admin-tab-schedules">Schedules</TabsTrigger>
            <TabsTrigger value="emergencies" data-testid="admin-tab-emergencies">Emergencies</TabsTrigger>
          </TabsList>

          <TabsContent value="users" className="mt-6">
            <div className="bg-white rounded-2xl border border-ayana-line overflow-x-auto" data-testid="admin-users-table">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Phone</TableHead>
                    <TableHead>Onboarding</TableHead>
                    <TableHead>Activated</TableHead>
                    <TableHead>Parents</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell className="font-medium">{u.name}</TableCell>
                      <TableCell>{u.email}</TableCell>
                      <TableCell>{u.phone}</TableCell>
                      <TableCell>
                        {u.onboarding_complete
                          ? <span className="text-ayana-primary">Complete</span>
                          : <span className="text-ayana-muted">Step {u.onboarding_step}</span>}
                      </TableCell>
                      <TableCell>
                        {u.activated ? <span className="text-ayana-whatsapp">Yes</span> : "No"}
                      </TableCell>
                      <TableCell>{u.parents_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {usersTotal > USERS_PER_PAGE && (
                <PaginationBar
                  skip={usersSkip}
                  limit={USERS_PER_PAGE}
                  total={usersTotal}
                  onSkip={fetchUsers}
                />
              )}
            </div>
          </TabsContent>

          <TabsContent value="messages" className="mt-6">
            <div className="bg-white rounded-2xl border border-ayana-line overflow-x-auto" data-testid="admin-messages-table">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Message</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {messages.map((m) => (
                    <TableRow key={m.id}>
                      <TableCell className="max-w-md truncate">{m.body}</TableCell>
                      <TableCell>{m.category}</TableCell>
                      <TableCell>
                        <span className={`text-xs px-2 py-1 rounded-full ${
                          m.status === "sent"
                            ? "bg-ayana-whatsapp/15 text-ayana-whatsapp"
                            : m.status === "simulated"
                            ? "bg-ayana-primary/10 text-ayana-primary"
                            : "bg-red-100 text-red-600"
                        }`}>
                          {m.status}
                        </span>
                      </TableCell>
                      <TableCell>{new Date(m.created_at).toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {messagesTotal > MSGS_PER_PAGE && (
                <PaginationBar
                  skip={messagesSkip}
                  limit={MSGS_PER_PAGE}
                  total={messagesTotal}
                  onSkip={fetchMessages}
                />
              )}
            </div>
          </TabsContent>

          <TabsContent value="delivery-health" className="mt-6" data-testid="admin-delivery-health-tab">
            <DeliveryHealthTab data={deliveryHealth} onRangeChange={fetchDeliveryHealth} />
          </TabsContent>

          <TabsContent value="schedules" className="mt-6">
            <div className="bg-white rounded-2xl border border-ayana-line overflow-x-auto" data-testid="admin-schedules-table">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Parent</TableHead>
                    <TableHead>Owner</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead>Messages</TableHead>
                    <TableHead>Active</TableHead>
                    <TableHead>Recovery</TableHead>
                    <TableHead>Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {schedules.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="font-medium">{s.parent_name}</TableCell>
                      <TableCell className="text-sm text-ayana-secondary">{s.user_name}</TableCell>
                      <TableCell>{s.mode}</TableCell>
                      <TableCell>{s.message_count}</TableCell>
                      <TableCell>
                        <span className={`text-xs px-2 py-1 rounded-full ${
                          s.active ? "bg-ayana-whatsapp/15 text-ayana-whatsapp" : "bg-ayana-muted/20 text-ayana-muted"
                        }`}>{s.active ? "Yes" : "No"}</span>
                      </TableCell>
                      <TableCell>
                        {s.recovery_mode && <span className="text-xs text-ayana-accent">until {s.recovery_until || "—"}</span>}
                      </TableCell>
                      <TableCell>{new Date(s.created_at).toLocaleDateString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {schedulesTotal > USERS_PER_PAGE && (
                <PaginationBar
                  skip={schedulesSkip}
                  limit={USERS_PER_PAGE}
                  total={schedulesTotal}
                  onSkip={fetchSchedules}
                />
              )}
            </div>
          </TabsContent>

          <TabsContent value="emergencies" className="mt-6">
            <div className="bg-white rounded-2xl border border-ayana-line overflow-x-auto" data-testid="admin-emergencies-table">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Phone</TableHead>
                    <TableHead>Message</TableHead>
                    <TableHead>Keywords</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {emergencies.map((e) => (
                    <TableRow key={e.id}>
                      <TableCell>{e.phone}</TableCell>
                      <TableCell className="max-w-xs truncate">{e.body}</TableCell>
                      <TableCell>
                        <span className="text-xs text-ayana-accent">
                          {(e.keywords || []).join(", ")}
                        </span>
                      </TableCell>
                      <TableCell>{e.status}</TableCell>
                      <TableCell>{new Date(e.created_at).toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

// ─── Delivery health ─────────────────────────────────────────────────────────
// Backed by /admin/delivery-health, which reads delivered_at/read_at/failed_at
// on message_logs — populated by the WhatsApp webhook's status callbacks (see
// _apply_wa_delivery_status() in server.py). Before that wiring existed,
// message_logs.status just froze at "sent" forever regardless of what Meta
// actually did with the message, so this is the first place in the app that
// shows real delivered/read/failed outcomes rather than send attempts.
const DAY_RANGES = [7, 14, 30];

function pct(n) {
  return n == null ? "—" : `${Math.round(n * 100)}%`;
}

function DeliveryHealthTab({ data, onRangeChange }) {
  const [days, setDays] = useState(7);
  const [rangeLoading, setRangeLoading] = useState(false);

  const changeDays = async (d) => {
    setDays(d);
    setRangeLoading(true);
    try {
      await onRangeChange(d);
    } finally {
      setRangeLoading(false);
    }
  };

  if (!data) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="w-6 h-6 animate-spin text-ayana-primary" />
      </div>
    );
  }

  const { overall, daily, stuck_sends: stuckSends, failing_parents: failingParents = [] } = data;

  const funnelData = [
    { name: "Sent",      value: overall.total,     fill: CHART_COLORS.muted },
    { name: "Delivered", value: overall.delivered, fill: CHART_COLORS.sky },
    { name: "Read",      value: overall.read,      fill: CHART_COLORS.whatsapp },
  ];

  const dailyChartData = [...daily].reverse().map((d) => ({
    day: d.day_key?.slice(5) || d.day_key, // MM-DD
    Delivered: d.delivered,
    Read: d.read,
    Failed: d.failed,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-ayana-secondary">
          Delivery confirmations from WhatsApp's own status callbacks — not just what we attempted to send.
        </p>
        <div className="flex gap-1.5" data-testid="delivery-health-range">
          {DAY_RANGES.map((d) => (
            <button
              key={d}
              onClick={() => changeDays(d)}
              disabled={rangeLoading}
              data-testid={`delivery-health-range-${d}`}
              className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                days === d
                  ? "bg-ayana-primary text-white border-ayana-primary"
                  : "border-ayana-line text-ayana-secondary hover:bg-ayana-alt"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4" data-testid="delivery-health-stats">
        <StatCard icon={MessageCircle} label="Sent" value={overall.total} color="muted" />
        <StatCard icon={CheckCircle2} label="Delivered" value={overall.delivered} sub={pct(overall.delivery_rate)} color="sky" />
        <StatCard icon={CheckCircle2} label="Read" value={overall.read} sub={pct(overall.read_rate)} color="whatsapp" />
        <StatCard icon={AlertTriangle} label="Failed" value={overall.failed} sub={pct(overall.failure_rate)} color="danger" />
        <StatCard icon={Activity} label="Pending" value={overall.pending} sub="no confirmation yet" color="gold" />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="bg-white rounded-2xl border border-ayana-line p-5">
          <h3 className="font-display text-sm font-medium text-ayana-text mb-3">Delivery funnel</h3>
          <ResponsiveContainer width="100%" height={240}>
            <FunnelChart>
              <Tooltip />
              <Funnel dataKey="value" data={funnelData} isAnimationActive>
                <LabelList position="right" fill="#2C2C2C" stroke="none" dataKey="name" />
              </Funnel>
            </FunnelChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-2xl border border-ayana-line p-5">
          <h3 className="font-display text-sm font-medium text-ayana-text mb-3">Daily outcomes</h3>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={dailyChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#EEE" />
              <XAxis dataKey="day" fontSize={11} />
              <YAxis fontSize={11} allowDecimals={false} />
              <Tooltip />
              <Legend />
              <Area type="monotone" dataKey="Delivered" stackId="1" stroke={CHART_COLORS.sky} fill={CHART_COLORS.sky} fillOpacity={0.4} />
              <Area type="monotone" dataKey="Read" stackId="2" stroke={CHART_COLORS.whatsapp} fill={CHART_COLORS.whatsapp} fillOpacity={0.4} />
              <Area type="monotone" dataKey="Failed" stackId="3" stroke={CHART_COLORS.danger} fill={CHART_COLORS.danger} fillOpacity={0.4} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-ayana-line overflow-x-auto" data-testid="delivery-health-stuck">
        <div className="p-5 pb-0">
          <h3 className="font-display text-sm font-medium text-ayana-text">
            Stuck sends <span className="text-ayana-muted font-normal">— sent 2h+ ago, no delivery confirmation or failure yet</span>
          </h3>
        </div>
        {stuckSends.length === 0 ? (
          <p className="p-5 text-sm text-ayana-muted">None — every recent send has resolved to delivered, read, or failed.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Parent</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Sent</TableHead>
                <TableHead>Has message ID</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stuckSends.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.parent_name}</TableCell>
                  <TableCell>{s.category}</TableCell>
                  <TableCell>{new Date(s.created_at).toLocaleString()}</TableCell>
                  <TableCell>
                    {s.has_sid ? (
                      <span className="text-ayana-muted text-xs">yes — waiting on Meta</span>
                    ) : (
                      <span className="text-red-600 text-xs">no — send likely never reached Meta</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <div className="bg-white rounded-2xl border border-ayana-line overflow-x-auto" data-testid="delivery-health-failing">
        <div className="p-5 pb-0">
          <h3 className="font-display text-sm font-medium text-ayana-text">
            Failing sends — per parent{" "}
            <span className="text-ayana-muted font-normal">
              — a scheduled message that keeps failing and has <em>not</em> gone through yet (silent drop; scheduler is still retrying)
            </span>
          </h3>
        </div>
        {failingParents.length === 0 ? (
          <p className="p-5 text-sm text-ayana-muted">None — no parent has an unresolved failing message in this window. 💛</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Parent</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>Day</TableHead>
                <TableHead>Failures</TableHead>
                <TableHead>Last try</TableHead>
                <TableHead>Last error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {failingParents.map((f, i) => (
                <TableRow key={`${f.parent_phone || f.parent_name}-${f.category}-${f.day_key}-${i}`} data-testid="failing-parent-row">
                  <TableCell className="font-medium">
                    {f.parent_name}
                    {f.parent_phone && <div className="text-xs text-ayana-muted">{f.parent_phone}</div>}
                  </TableCell>
                  <TableCell className="text-xs text-ayana-secondary">{f.owner_email || "—"}</TableCell>
                  <TableCell>{f.category}</TableCell>
                  <TableCell className="text-xs">{f.day_key}</TableCell>
                  <TableCell>
                    <span className="inline-flex items-center justify-center min-w-[1.5rem] px-1.5 py-0.5 rounded-full bg-red-100 text-red-700 text-xs font-semibold">
                      {f.failures}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs">{f.last_attempt_at ? new Date(f.last_attempt_at).toLocaleString() : "—"}</TableCell>
                  <TableCell className="text-xs text-red-600 max-w-[16rem] truncate" title={f.last_error || ""}>
                    {f.last_error || "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}