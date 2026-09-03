import { useState } from "react";
import { Link } from "react-router-dom";
import {
  MessageCircle, Globe, ShieldCheck, ArrowRight, Check, Mic, Clock, Languages,
  PlayCircle, Heart, ArrowUpRight, AlertTriangle, Sparkles, Gift, Users, X,
} from "lucide-react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { HighlightText } from "@/components/HighlightText";
import { PricingCards } from "@/components/PricingCards";
import { Logo } from "@/components/Logo";
import { PhoneMockup } from "@/components/PhoneMockup";
import { useAuth } from "@/context/AuthContext";
import { useLang } from "@/context/LanguageContext";
import { StartConnectingModal } from "@/components/StartConnectingModal";
import { FALLBACK_PLANS, FALLBACK_CURRENCIES } from "../lib/fallbackPlans";

const IMG = {
  amma:  "/ayana_amma.png",
  nanna: "/ayana_nanna.png",
  hands: "/ayana_hands.png",
  child: "/ayana_child.png",
};

// Walkthrough video: place the file at public/videos/ayana_video_walkthrough_engl.mp4
// (a local Windows path like C:\Users\... cannot be referenced by a deployed web app).
const WALKTHROUGH_VIDEO_SRC = "/videos/ayana_video_walkthrough_engl.mp4";

const LANGS = [["en", "EN"], ["te", "తె"], ["hi", "हिं"]];
const trackEvent = (name, props) => { if (window.gtag) window.gtag("event", name, props); };

function LangSwitch({ lang, setLang }) {
  return (
    <div className="flex items-center gap-0.5 rounded-full p-1 border border-ayana-gold/40 bg-white/70" data-testid="lang-switcher">
      {LANGS.map(([code, label]) => (
        <button key={code} onClick={() => setLang(code)} data-testid={`lang-switcher-${code}`}
          className={`px-2.5 py-1 rounded-full text-xs font-bold transition-colors ${lang === code ? "bg-ayana-gold text-white shadow-sm" : "text-ayana-secondary hover:text-ayana-text"}`}>
          {label}
        </button>
      ))}
    </div>
  );
}

// Small elegant eyebrow: gold rule + instrument-serif italic label
function Eyebrow({ children, center = false }) {
  return (
    <div className={`flex items-center gap-3 mb-5 ${center ? "justify-center" : ""}`}>
      <span className="h-px w-8 bg-ayana-gold/60" />
      <span className="font-instrument italic text-ayana-gold text-lg sm:text-xl">{children}</span>
    </div>
  );
}

// Mini WhatsApp chat panel used in the "What Amma Sees" section
const CHAT_DATA = {
  en: {
    name: "Amma",
    time: "8:02 AM",
    msg: "Good morning Amma! 🌞 How are you feeling today?",
    buttons: ["Good 😊", "Okay 🙂", "Not well 😟"],
  },
  te: {
    name: "అమ్మ",
    time: "8:02 AM",
    msg: "శుభోదయం అమ్మా! 🌞 ఈరోజు ఎలా ఉన్నారు?",
    buttons: ["బాగున్నా 😊", "పరవాలేదు 🙂", "బాలేదు 😟"],
  },
  hi: {
    name: "अम्मा",
    time: "8:02 AM",
    msg: "सुप्रभात अम्मा! 🌞 आज कैसा महसूस कर रही हैं?",
    buttons: ["अच्छा 😊", "ठीक है 🙂", "ठीक नहीं 😟"],
  },
};

function MiniChatPanel({ langCode, isActive }) {
  const data = CHAT_DATA[langCode];
  return (
    <div className={`rounded-2xl overflow-hidden shadow-lg border transition-all duration-300 ${isActive ? "border-[#25D366]/60 shadow-[#25D366]/10 scale-[1.02]" : "border-ayana-line opacity-75"}`}>
      {/* WA header */}
      <div className="bg-[#075E54] px-4 py-3 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-ayana-gold/30 flex items-center justify-center text-base">👵</div>
        <div>
          <p className="text-white text-sm font-semibold leading-none">{data.name}</p>
          <p className="text-white/60 text-[11px] mt-0.5">via AYANA · online</p>
        </div>
        <span className="ml-auto w-2 h-2 rounded-full bg-[#25D366] animate-pulse" />
      </div>
      {/* Chat area */}
      <div className="bg-[#0B141A] px-3 py-4 space-y-3 min-h-[160px]">
        {/* AYANA bubble */}
        <div className="max-w-[88%] bg-[#1F2C34] rounded-2xl rounded-tl-sm px-3.5 py-2.5">
          <p className="text-white text-[12px] leading-relaxed">{data.msg}</p>
          <p className="text-white/40 text-[10px] text-right mt-1">{data.time} ✓</p>
        </div>
        {/* Quick-reply buttons */}
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {data.buttons.map((btn, i) => (
            <span key={i} className="inline-block rounded-full border border-[#00A884]/70 bg-[#0B141A] text-[#00A884] text-[11px] font-medium px-2.5 py-1 leading-none">
              {btn}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// Simple lightbox for the walkthrough video
function VideoWalkthroughModal({ open, onClose, src }) {
  const [errored, setErrored] = useState(false);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm px-4"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl rounded-2xl overflow-hidden shadow-2xl bg-black"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          aria-label="Close video"
          className="absolute top-3 right-3 z-10 w-9 h-9 rounded-full bg-white/90 flex items-center justify-center hover:bg-white transition-colors"
        >
          <X className="w-4 h-4 text-ayana-text" />
        </button>

        {errored ? (
          <div className="p-12 text-center text-white/85 text-sm leading-relaxed">
            Couldn't load the walkthrough video.<br />
            Make sure the file exists at <code className="text-ayana-gold">public{src}</code> in your project
            (check the exact filename and extension match).
          </div>
        ) : (
          // No autoPlay: most browsers block autoplay, which made this look
          // "broken" even when the code was fine. Controls let the user press play.
          <video
            src={src}
            controls
            className="w-full h-auto max-h-[80vh] bg-black"
            onError={() => setErrored(true)}
          />
        )}
      </div>
    </div>
  );
}

export default function Landing() {
  const { config } = useAuth();
  const { t, lang, setLang } = useLang();

  const [modalOpen, setModalOpen] = useState(false);
  const [demoLang, setDemoLang] = useState("en");
  const [videoOpen, setVideoOpen] = useState(false);

  const steps        = t("how.steps");
  const faqItems     = t("faq.items");
  const globalPoints = t("global.points");
  const safetyT      = t("safety");
  const extrasT      = t("extras");
  const demoT        = t("whatsappDemo");

  return (
    <div data-lang={lang} className="relative min-h-screen overflow-x-hidden bg-warm-cream text-ayana-text">

      {/* HEADER */}
      <header className="sticky top-0 z-50 border-b border-ayana-line/60 backdrop-blur-xl" style={{ background: "rgba(251,246,236,0.8)" }}>
        <div className="max-w-7xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">
          <Link to="/" data-testid="nav-logo"><Logo size={38} /></Link>
          <nav className="hidden lg:flex items-center gap-9 text-[13px] uppercase tracking-[0.14em] text-ayana-secondary">
            {[["#how", t("nav.how")], ["#trust", t("nav.trust")], ["#pricing", t("nav.pricing")], ["#faq", t("nav.faq")]].map(([href, label]) => (
              <a key={href} href={href} className="hover:text-ayana-gold transition-colors">{label}</a>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            <LangSwitch lang={lang} setLang={setLang} />
            <Link to="/login" data-testid="nav-login" className="hidden sm:inline text-sm font-semibold text-ayana-secondary hover:text-ayana-text transition-colors">{t("nav.login")}</Link>
            <Link to="/signup" data-testid="nav-signup" className="btn-saffron text-sm font-semibold px-5 py-2 rounded-full">{t("nav.signup")}</Link>
          </div>
        </div>
      </header>

      <main className="relative z-10">

        {/* HERO */}
        <section className="relative bg-warm-peach overflow-hidden">
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute -top-32 -right-10 w-[560px] h-[560px] rounded-full blur-3xl" style={{ background: "rgba(212,150,10,0.20)" }} />
            <div className="absolute bottom-0 -left-24 w-[440px] h-[440px] rounded-full blur-3xl" style={{ background: "rgba(232,89,12,0.07)" }} />
          </div>

          <div className="relative max-w-7xl mx-auto px-5 sm:px-8 pt-14 pb-24 lg:pt-20 lg:pb-32 grid lg:grid-cols-[1.05fr_0.95fr] gap-12 lg:gap-8 items-center">
            <div>
              <Eyebrow>{t("hero.badge")}</Eyebrow>

              <h1 className="font-display font-black leading-[0.98] text-ayana-text text-[2.65rem] sm:text-6xl lg:text-[4.6rem]">
                <HighlightText text={t("hero.title")} ranges={[[0, 0.32]]} colors={["text-gradient-gold"]} />
              </h1>
              <div className="mt-5 h-px w-28 bg-gradient-to-r from-ayana-gold via-ayana-accent to-transparent" />

              <p className="font-serif text-2xl sm:text-[1.7rem] leading-snug text-ayana-secondary mt-6 max-w-xl">
                {t("hero.subtitle")}
              </p>

              <div className="mt-9 flex flex-col sm:flex-row gap-4">
                <button data-testid="hero-cta" onClick={() => { trackEvent("cta_click", { id: "hero" }); setModalOpen(true); }}
                  className="btn-saffron btn-tactile inline-flex items-center justify-center gap-2 px-8 py-4 rounded-full font-semibold text-base">
                  {t("hero.ctaPrimary")} <ArrowRight className="w-4 h-4" strokeWidth={2.5} />
                </button>
                <a href="#how" data-testid="hero-cta-secondary"
                  className="btn-outline-warm inline-flex items-center justify-center px-8 py-4 rounded-full font-semibold text-base">
                  {t("hero.ctaSecondary")}
                </a>
              </div>

              <div className="mt-10 flex flex-wrap gap-x-7 gap-y-3">
                {[{ icon: Languages, text: t("hero.t1") }, { icon: Clock, text: t("hero.t2") }, { icon: Check, text: t("hero.t3") }].map(({ icon: Icon, text }) => (
                  <span key={text} className="inline-flex items-center gap-2 text-sm text-ayana-secondary">
                    <Icon className="w-4 h-4 text-ayana-gold shrink-0" /> {text}
                  </span>
                ))}
              </div>
            </div>

            {/* Editorial image + phone */}
            <div className="relative mx-auto w-full max-w-md lg:max-w-none">
              <div className="relative">
                <span className="absolute -top-4 -right-2 sm:-right-4 z-20 rounded-full bg-white shadow-lg border border-ayana-line px-4 py-2 text-xs font-semibold text-ayana-text flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#25D366] animate-pulse" /> Amma is online
                </span>
                <div className="absolute -inset-3 rounded-[2.6rem] blur-2xl" style={{ background: "linear-gradient(135deg, rgba(212,150,10,0.35), rgba(232,89,12,0.14))" }} />
                <div className="relative rounded-[2.2rem] overflow-hidden shadow-2xl ring-1 ring-ayana-gold/25">
                  <img src={IMG.amma} alt="A loving elderly Indian mother" className="w-full h-[380px] sm:h-[480px] lg:h-[560px] object-cover" />
                  <div className="absolute inset-0 bg-gradient-to-t from-[#2a1c05]/35 via-transparent to-transparent" />
                </div>
              </div>
              <div className="absolute -bottom-10 -left-4 sm:-left-10 scale-[0.7] sm:scale-[0.8] origin-bottom-left">
                <PhoneMockup lang={lang} />
              </div>
            </div>
          </div>
        </section>

        {/* HOW IT WORKS: editorial numbered */}
        <section id="how" className="bg-warm-cream">
          <div className="max-w-7xl mx-auto px-5 sm:px-8 py-20 lg:py-28 grid lg:grid-cols-2 gap-14 lg:gap-20 items-center">
            <div className="relative order-2 lg:order-1">
              <div className="absolute -inset-3 rounded-[2.5rem] blur-2xl" style={{ background: "linear-gradient(135deg, rgba(212,150,10,0.28), rgba(10,89,64,0.10))" }} />
              <div className="relative rounded-[2rem] overflow-hidden shadow-xl ring-1 ring-ayana-gold/20">
                <img src={IMG.hands} alt="Elderly hands holding a phone" className="w-full h-[360px] sm:h-[460px] object-cover" />
              </div>
            </div>

            <div className="order-1 lg:order-2">
              <Eyebrow>{t("how.label")}</Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-5xl leading-[1.05] text-ayana-text">
                <HighlightText text={t("how.title")} ranges={[[0.5, 1.0]]} colors={["text-gradient-gold"]} />
              </h2>
              <p className="font-serif text-xl sm:text-2xl text-ayana-secondary mt-4 leading-snug">{t("how.sub")}</p>

              <ol className="mt-9 divide-y divide-ayana-line/70 border-t border-ayana-line/70">
                {steps.map((step, i) => (
                  <li key={i} className="flex items-start gap-5 py-5 group">
                    <span className="font-display text-3xl font-bold text-gradient-gold w-10 shrink-0 leading-none">{`0${i + 1}`}</span>
                    <div>
                      <h3 className="font-display text-lg font-bold text-ayana-text">{step.title}</h3>
                      <p className="text-[15px] text-ayana-secondary leading-relaxed mt-1">{step.desc}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </section>

        {/* DEMO / how to reply */}
        <section id="training" className="bg-warm-gold">
          <div className="max-w-7xl mx-auto px-5 sm:px-8 py-20 lg:py-28 grid lg:grid-cols-2 gap-14 items-center">
            <div className="flex justify-center order-2 lg:order-1">
              <div className="relative">
                <PhoneMockup lang={lang} />
                <button
                  type="button"
                  onClick={() => { trackEvent("video_walkthrough_open", { id: "training" }); setVideoOpen(true); }}
                  className="absolute -bottom-4 left-1/2 -translate-x-1/2 inline-flex items-center gap-1.5 text-xs font-semibold text-ayana-secondary bg-white px-3 py-1.5 rounded-full border border-ayana-line shadow-sm whitespace-nowrap hover:border-ayana-gold/50 transition-colors"
                >
                  <PlayCircle className="w-3.5 h-3.5 text-ayana-accent" /> {t("training.watchCta")}
                </button>
              </div>
            </div>
            <div className="order-1 lg:order-2">
              <Eyebrow>{t("training.label")}</Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-5xl leading-[1.05] text-ayana-text">
                <HighlightText text={t("training.title")} ranges={[[0.5, 1.0]]} colors={["text-gradient-gold"]} />
              </h2>
              <p className="font-serif text-xl sm:text-2xl text-ayana-secondary mt-4 leading-snug">{t("training.sub")}</p>

              <div className="mt-8 space-y-3">
                {t("training.steps").map((step, i) => {
                  const Icon = [MessageCircle, Mic, Check][i];
                  return (
                    <div key={i} className="flex items-start gap-4 rounded-2xl border border-ayana-line bg-white/80 p-4 sm:p-5 shadow-sm">
                      <span className="icon-well-gold w-10 h-10 rounded-xl flex items-center justify-center shrink-0">
                        <Icon className="w-5 h-5" strokeWidth={1.75} />
                      </span>
                      <div>
                        <h3 className="font-display text-base font-bold text-ayana-text">{step.title}</h3>
                        <p className="text-sm text-ayana-secondary leading-relaxed mt-0.5">{step.desc}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="mt-5 text-xs text-ayana-muted leading-relaxed">{t("training.fallbackNote")}</p>
            </div>
          </div>
        </section>

        {/* WHAT AMMA SEES: multilingual WhatsApp button demo */}
        <section id="what-they-see" className="bg-warm-cream">
          <div className="max-w-7xl mx-auto px-5 sm:px-8 py-20 lg:py-28">
            <div className="text-center max-w-2xl mx-auto mb-12">
              <Eyebrow center>{demoT.label}</Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-5xl leading-[1.05] text-ayana-text">
                <HighlightText text={demoT.title} ranges={[[0, 0.3]]} colors={["text-gradient-gold"]} />
              </h2>
              <p className="font-serif text-xl sm:text-2xl text-ayana-secondary mt-4">{demoT.sub}</p>
            </div>

            {/* Language selector pills */}
            <div className="flex justify-center gap-2 mb-8">
              {Object.entries(demoT.langLabels).map(([code, label]) => (
                <button
                  key={code}
                  onClick={() => setDemoLang(code)}
                  className={`px-5 py-2 rounded-full text-sm font-semibold border transition-all ${
                    demoLang === code
                      ? "bg-ayana-gold text-white border-ayana-gold shadow-sm"
                      : "bg-white text-ayana-secondary border-ayana-line hover:border-ayana-gold/50"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Three chat panels: one per language, active one highlighted */}
            <div className="grid sm:grid-cols-3 gap-4 max-w-4xl mx-auto">
              {["en", "te", "hi"].map((code) => (
                <div key={code} onClick={() => setDemoLang(code)} className="cursor-pointer">
                  <MiniChatPanel langCode={code} isActive={demoLang === code} />
                </div>
              ))}
            </div>

            {/* Badge */}
            <div className="mt-8 flex justify-center">
              <span className="inline-flex items-center gap-2 text-xs font-medium text-ayana-secondary bg-white border border-ayana-line px-4 py-2 rounded-full shadow-sm">
                <MessageCircle className="w-3.5 h-3.5 text-[#25D366]" />
                {demoT.badge}
              </span>
            </div>
          </div>
        </section>

        {/* GLOBAL: big statement */}
        <section className="bg-warm-peach relative overflow-hidden">
          <div className="max-w-7xl mx-auto px-5 sm:px-8 py-20 lg:py-28 grid lg:grid-cols-12 gap-14 items-center">
            <div className="lg:col-span-7">
              <Eyebrow><span className="inline-flex items-center gap-2"><Globe className="w-4 h-4" /> {t("global.label")}</span></Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-[3.2rem] leading-[1.03] text-ayana-text">
                <HighlightText text={t("global.title")} ranges={[[0, 0.28]]} colors={["text-gradient-gold"]} />
              </h2>
              <p className="font-serif text-xl sm:text-2xl text-ayana-secondary mt-5 leading-snug max-w-2xl">{t("global.sub")}</p>
              <ul className="mt-9 space-y-4 max-w-xl">
                {globalPoints.map((p, i) => (
                  <li key={i} className="flex items-start gap-4">
                    <span className="icon-well-gold w-9 h-9 rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                      {[<Clock key="c" className="w-4 h-4" />, <Mic key="m" className="w-4 h-4" />, <ShieldCheck key="s" className="w-4 h-4" />][i]}
                    </span>
                    <span className="text-ayana-text/80 leading-relaxed pt-1">{p}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="lg:col-span-5">
              <div className="relative">
                <div className="absolute -inset-3 rounded-[2.5rem] blur-2xl" style={{ background: "linear-gradient(135deg, rgba(232,89,12,0.16), rgba(212,150,10,0.24))" }} />
                <div className="relative rounded-[2rem] overflow-hidden shadow-xl ring-1 ring-ayana-gold/20">
                  <img src={IMG.child} alt="Adult child staying connected from abroad" className="w-full h-[400px] sm:h-[480px] object-cover" />
                </div>
                <div className="absolute -bottom-5 -left-5 rounded-2xl px-5 py-3.5 flex items-center gap-3 animate-float shadow-lg border border-ayana-line bg-white">
                  <span className="w-9 h-9 rounded-full flex items-center justify-center" style={{ background: "rgba(37,211,102,0.15)" }}>
                    <MessageCircle className="w-4 h-4" style={{ color: "#25D366" }} fill="currentColor" />
                  </span>
                  <div>
                    <p className="text-xs font-bold text-ayana-text">Message delivered</p>
                    <p className="text-xs text-ayana-muted">{'Amma: "Feeling good 😊"'}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* AI GUARDIAN: safety / distress detection */}
        <section id="safety" className="bg-warm-cream">
          <div className="max-w-7xl mx-auto px-5 sm:px-8 py-20 lg:py-28">
            <div className="text-center max-w-2xl mx-auto mb-14">
              <Eyebrow center>
                <span className="inline-flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4" /> {safetyT.label}
                </span>
              </Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-5xl leading-[1.05] text-ayana-text">
                <HighlightText text={safetyT.title} ranges={[[0.55, 1.0]]} colors={["text-gradient-gold"]} />
              </h2>
              <p className="font-serif text-xl sm:text-2xl text-ayana-secondary mt-4 leading-snug">{safetyT.sub}</p>
            </div>

            <div className="grid md:grid-cols-3 gap-6 max-w-5xl mx-auto">
              {/* Card 1: keyword watch */}
              <div className="rounded-2xl border border-ayana-line bg-white p-6 shadow-sm flex flex-col gap-4">
                <span className="w-12 h-12 rounded-xl bg-amber-50 border border-amber-200 flex items-center justify-center text-xl shrink-0">🔍</span>
                <div>
                  <h3 className="font-display text-lg font-bold text-ayana-text">{safetyT.card1Title}</h3>
                  <p className="text-[15px] text-ayana-secondary leading-relaxed mt-2">{safetyT.card1Desc}</p>
                </div>
              </div>

              {/* Card 2: AI voice analysis, featured */}
              <div className="rounded-2xl border-2 border-ayana-gold/40 bg-white p-6 shadow-lg flex flex-col gap-4 relative overflow-hidden">
                <div className="absolute top-0 right-0 w-24 h-24 rounded-full blur-2xl" style={{ background: "rgba(212,150,10,0.12)" }} />
                <span className="relative z-10 w-12 h-12 rounded-xl flex items-center justify-center text-xl shrink-0" style={{ background: "rgba(212,150,10,0.10)", border: "1px solid rgba(212,150,10,0.25)" }}>🎤</span>
                <div className="relative z-10">
                  <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-ayana-gold bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full mb-2">
                    <Sparkles className="w-2.5 h-2.5" /> AI-powered
                  </span>
                  <h3 className="font-display text-lg font-bold text-ayana-text">{safetyT.card2Title}</h3>
                  <p className="text-[15px] text-ayana-secondary leading-relaxed mt-2">{safetyT.card2Desc}</p>
                </div>
              </div>

              {/* Card 3: one tap */}
              <div className="rounded-2xl border border-ayana-line bg-white p-6 shadow-sm flex flex-col gap-4">
                <span className="w-12 h-12 rounded-xl bg-red-50 border border-red-200 flex items-center justify-center text-xl shrink-0">📞</span>
                <div>
                  <h3 className="font-display text-lg font-bold text-ayana-text">{safetyT.card3Title}</h3>
                  <p className="text-[15px] text-ayana-secondary leading-relaxed mt-2">{safetyT.card3Desc}</p>
                </div>
              </div>
            </div>

            {/* Alert note */}
            <div className="mt-8 max-w-xl mx-auto flex items-start gap-3 rounded-2xl border border-red-200/60 bg-red-50/50 px-5 py-4">
              <AlertTriangle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
              <p className="text-sm text-ayana-secondary leading-relaxed">{safetyT.note}</p>
            </div>
          </div>
        </section>

        {/* TRUST */}
        <section id="trust" className="bg-warm-peach">
          <div className="max-w-7xl mx-auto px-5 sm:px-8 py-20 lg:py-28 grid lg:grid-cols-12 gap-14 items-center">
            <div className="lg:col-span-6">
              <div className="relative">
                <div className="absolute -inset-3 rounded-[2.5rem] blur-2xl" style={{ background: "linear-gradient(135deg, rgba(212,150,10,0.28), rgba(10,89,64,0.08))" }} />
                <div className="relative rounded-[2rem] overflow-hidden shadow-xl ring-1 ring-ayana-gold/20">
                  <img src={IMG.nanna} alt="A warm elderly Indian couple" className="w-full h-[400px] sm:h-[500px] object-cover" />
                </div>
                <div className="absolute -top-5 -right-5 rounded-2xl px-5 py-3.5 flex items-center gap-3 shadow-lg border border-ayana-line bg-white animate-float">
                  <span className="w-9 h-9 rounded-full flex items-center justify-center" style={{ background: "rgba(212,150,10,0.16)" }}>
                    <ShieldCheck className="w-4 h-4 text-ayana-gold" />
                  </span>
                  <div>
                    <p className="text-xs font-bold text-ayana-text">Private &amp; secure</p>
                    <p className="text-xs text-ayana-muted">No data sold, ever</p>
                  </div>
                </div>
              </div>
            </div>
            <div className="lg:col-span-6">
              <Eyebrow>{t("trust.label")}</Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-[3rem] leading-[1.05] text-ayana-text">
                <HighlightText text={t("trust.title")} ranges={[[0.45, 0.75]]} colors={["text-gradient-gold"]} />
              </h2>
              <p className="font-serif text-xl sm:text-2xl text-ayana-secondary mt-4 leading-snug">{t("trust.sub")}</p>
              <div className="mt-8 space-y-4">
                {["note2", "note3"].map((key) => (
                  <div key={key} className="flex items-start gap-4 rounded-2xl border border-ayana-line bg-white p-5 shadow-sm">
                    <span className="icon-well-gold w-9 h-9 rounded-lg flex items-center justify-center shrink-0 mt-0.5">
                      <Heart className="w-4 h-4" strokeWidth={2} />
                    </span>
                    <p className="text-ayana-text/80 leading-relaxed text-[15px]">{t(`trust.${key}`)}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* A LITTLE MORE LOVE: emotional feature highlights */}
        <section className="bg-warm-gold">
          <div className="max-w-7xl mx-auto px-5 sm:px-8 py-20 lg:py-24">
            <div className="text-center max-w-2xl mx-auto mb-12">
              <Eyebrow center>{extrasT.label}</Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-5xl leading-[1.05] text-ayana-text">
                <HighlightText text={extrasT.title} ranges={[[0.55, 1.0]]} colors={["text-gradient-gold"]} />
              </h2>
              <p className="font-serif text-xl sm:text-2xl text-ayana-secondary mt-4">{extrasT.sub}</p>
            </div>

            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
              {extrasT.items.map((item, i) => (
                <div key={i} className="rounded-2xl border border-ayana-line bg-white p-6 shadow-sm flex flex-col gap-3">
                  <span className="text-3xl">{item.icon}</span>
                  <h3 className="font-display text-base font-bold text-ayana-text leading-tight">{item.title}</h3>
                  <p className="text-sm text-ayana-secondary leading-relaxed">{item.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* PRICING */}
        <section id="pricing" className="bg-warm-cream">
          <div className="max-w-5xl mx-auto px-5 sm:px-8 py-20 lg:py-28">
            <div className="text-center max-w-2xl mx-auto mb-12">
              <Eyebrow center>{t("pricing.label")}</Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-5xl leading-[1.05] text-ayana-text">
                <HighlightText text={t("pricing.title")} ranges={[[0, 0.3]]} colors={["text-gradient-gold"]} />
              </h2>
              <p className="font-serif text-xl sm:text-2xl text-ayana-secondary mt-4">{t("pricing.sub")}</p>
            </div>
            <PricingCards plans={config?.plans?.length ? config.plans : FALLBACK_PLANS} currencies={config?.currencies?.length ? config.currencies : FALLBACK_CURRENCIES} />

            <div className="mt-8 text-center">
              <Link to="/signup" data-testid="pricing-cta" onClick={() => trackEvent("cta_click", { id: "pricing" })}
                className="btn-saffron btn-tactile inline-flex items-center gap-2 px-8 py-4 rounded-full font-semibold">
                {t("pricing.cta")} <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="bg-warm-gold">
          <div className="max-w-3xl mx-auto px-5 sm:px-8 py-20 lg:py-28">
            <div className="text-center mb-12">
              <Eyebrow center>{t("faq.label")}</Eyebrow>
              <h2 className="font-display font-extrabold text-3xl sm:text-4xl lg:text-5xl leading-[1.05] text-ayana-text">
                <HighlightText text={t("faq.title")} ranges={[[0.6, 1.0]]} colors={["text-gradient-gold"]} />
              </h2>
            </div>
            <Accordion type="single" collapsible className="space-y-3" data-testid="faq-accordion">
              {faqItems.map((item, i) => (
                <AccordionItem key={i} value={`i-${i}`}
                  className="rounded-xl px-5 border border-ayana-line bg-white shadow-sm transition-all hover:border-ayana-gold/50"
                  data-testid={`faq-item-${i}`}>
                  <AccordionTrigger className="text-left font-display text-lg font-semibold text-ayana-text hover:no-underline py-5">
                    {item.q}
                  </AccordionTrigger>
                  <AccordionContent className="text-ayana-secondary leading-relaxed pb-5 text-[15px]">
                    {item.a}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </section>

        {/* FINAL CTA */}
        <section>
          <div className="relative overflow-hidden" style={{ background: "linear-gradient(135deg, #E8B84B 0%, #D4960A 45%, #E8590C 100%)" }}>
            <div className="absolute top-0 right-0 w-96 h-96 rounded-full blur-3xl -translate-y-1/2 translate-x-1/4" style={{ background: "rgba(255,255,255,0.16)" }} />
            <div className="absolute bottom-0 left-0 w-64 h-64 rounded-full blur-3xl translate-y-1/2 -translate-x-1/4" style={{ background: "rgba(0,0,0,0.08)" }} />
            <div className="relative max-w-4xl mx-auto px-5 sm:px-8 py-20 lg:py-28 text-center">
              <h2 className="font-display font-black text-white text-4xl sm:text-5xl lg:text-6xl leading-[1.02]">
                {t("finalCta.title")}
              </h2>
              <p className="font-serif text-2xl text-white/90 max-w-xl mx-auto mt-5">{t("finalCta.sub")}</p>
              <button data-testid="footer-cta" onClick={() => { trackEvent("cta_click", { id: "footer" }); setModalOpen(true); }}
                className="btn-tactile mt-10 inline-flex items-center gap-2 px-9 py-4 rounded-full bg-white font-bold shadow-2xl hover:bg-[#FFF8EE] transition-colors text-ayana-accent">
                {t("finalCta.cta")} <ArrowUpRight className="w-5 h-5" strokeWidth={2.5} />
              </button>
            </div>
          </div>
        </section>

        {/* FOOTER */}
        <footer className="bg-warm-cream border-t border-ayana-line">
          <div className="max-w-7xl mx-auto px-5 sm:px-8 py-14 grid md:grid-cols-2 gap-10 items-start">
            <div>
              <Logo size={44} className="mb-5" />
              <p className="font-serif text-lg leading-snug text-ayana-secondary max-w-md">{t("footer.tagline")}</p>
              <div className="mt-6 flex items-center gap-3 flex-wrap">
                <span className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border" style={{ color: "#128C4B", borderColor: "rgba(37,211,102,0.3)", background: "rgba(37,211,102,0.08)" }}>
                  <MessageCircle className="w-3.5 h-3.5" /> WhatsApp powered
                </span>
                <span className="inline-flex items-center gap-1.5 text-xs text-ayana-gold border border-ayana-gold/30 px-3 py-1.5 rounded-full" style={{ background: "rgba(212,150,10,0.08)" }}>
                  <ShieldCheck className="w-3.5 h-3.5" /> Secure &amp; private
                </span>
              </div>
            </div>
            <div className="md:text-right flex flex-col md:items-end gap-4 text-sm text-ayana-secondary">
              <div className="flex gap-5">
                <Link to="/privacy"    className="hover:text-ayana-gold transition-colors">Privacy</Link>
                <Link to="/terms"      className="hover:text-ayana-gold transition-colors">Terms</Link>
                <Link to="/disclaimer" className="hover:text-ayana-gold transition-colors">Disclaimer</Link>
              </div>
              <p className="text-xs max-w-xs text-ayana-muted">{t("footer.disclaimer")}</p>
              <p className="text-xs text-ayana-muted">© {new Date().getFullYear()} AYANA. Made with 💛</p>
            </div>
          </div>
        </footer>
      </main>
      <StartConnectingModal open={modalOpen} onClose={() => setModalOpen(false)} />
      <VideoWalkthroughModal open={videoOpen} onClose={() => setVideoOpen(false)} src={WALKTHROUGH_VIDEO_SRC} />
    </div>
  );
}