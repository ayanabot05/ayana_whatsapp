import { motion } from "framer-motion";
import { Signal, Wifi, BatteryFull, Check, CheckCheck, Mic } from "lucide-react";

/**
 * PhoneMockup
 * Reusable animated "phone in hand" mockup that plays out a WhatsApp-style
 * check-in conversation. Used in the Landing hero (right column) — built
 * as a standalone component so it can be reused anywhere else in the app
 * (e.g. onboarding preview, marketing sections) without copy-pasting markup.
 *
 * Props:
 *  - avatarSrc: image used as the parent's WhatsApp avatar
 *  - parentName: display name shown in the chat header
 *  - lang: "en" | "te" | "hi" (controls button labels)
 *  - messages: [{ from: "ayana" | "parent", text, time, voice?, buttons? }]
 *    When `buttons` is provided, renders WhatsApp-style quick-reply pills
 *    below the chat bubble.
 */

const BUTTON_LABELS = {
  en: {
    mood: ["Good 😊", "Okay 🙂", "Not well 😟"],
    medicine: ["Taken ✅", "Not yet", "Skipped"],
    reengagement: ["I'm fine", "Need help", "Call me"],
  },
  te: {
    mood: ["బాగున్నా 😊", "పరవాలేదు 🙂", "బాలేదు 😟"],
    medicine: ["వేసుకున్నా ✅", "ఇంకా లేదు", "వేసుకోలేదు"],
    reengagement: ["నేను బాగున్నాను", "సహాయం కావాలి", "కాల్ చేయండి"],
  },
  hi: {
    mood: ["अच्छा 😊", "ठीक है 🙂", "ठीक नहीं 😟"],
    medicine: ["ले लिया ✅", "अभी नहीं", "छोड़ दिया"],
    reengagement: ["मैं ठीक हूँ", "मदद चाहिए", "कॉल कीजिए"],
  },
};

const buildMessages = (lang = "en") => {
  const labels = BUTTON_LABELS[lang] || BUTTON_LABELS.en;
  const greetings = {
    en: "Good morning Amma! 🌞 How are you feeling today?",
    te: "శుభోదయం అమ్మా! 🌞 ఈరోజు ఎలా ఉన్నారు?",
    hi: "सुप्रभात अम्मा! 🌞 आज कैसा महसूस कर रही हैं?",
  };
  // Parent tapped "Good 😊" — reply is exactly the button label
  const replies = {
    en: labels.mood[0],   // "Good 😊"
    te: labels.mood[0],   // "బాగున్నా 😊"
    hi: labels.mood[0],   // "अच्छा 😊"
  };
  const medChecks = {
    en: "Time for your morning tablet 💊 Crocin — small white one!",
    te: "అమ్మా, మందుల టైం 💊 Crocin మాత్ర వేసుకోండి!",
    hi: "अम्मा, दवाई का समय 💊 Crocin गोली लेना है!",
  };

  return [
    {
      from: "ayana",
      text: greetings[lang] || greetings.en,
      time: "8:02 AM",
      buttons: labels.mood,
    },
    { from: "parent", text: replies[lang] || replies.en, time: "8:14 AM" },
    {
      from: "ayana",
      text: medChecks[lang] || medChecks.en,
      time: "8:15 AM",
      buttons: labels.medicine,
    },
    { from: "parent", text: "", time: "8:20 AM", voice: true },
  ];
};

const bubbleVariants = {
  hidden: { opacity: 0, y: 16, scale: 0.96 },
  show: (i) => ({
    opacity: 1, y: 0, scale: 1,
    transition: { delay: 0.8 + i * 0.5, duration: 0.45, ease: [0.22, 1, 0.36, 1] },
  }),
};

export function PhoneMockup({
  avatarSrc = "/img_parents.jpg",
  parentName = "Amma",
  lang = "en",
  messages,
  className = "",
}) {
  const msgs = messages || buildMessages(lang);

  return (
    <div className={`relative mx-auto w-[300px] sm:w-[320px] ${className}`}>
      {/* Glow behind the phone */}
      <div
        className="absolute -inset-6 rounded-[3rem] blur-2xl opacity-70"
        style={{ background: "linear-gradient(135deg, rgba(255,107,53,0.35), rgba(255,201,60,0.25))" }}
        aria-hidden="true"
      />

      {/* Phone chassis */}
      <div className="relative rounded-[2.5rem] border-[6px] border-[#111] bg-[#111] shadow-2xl overflow-hidden">
        {/* Notch */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-28 h-5 bg-[#111] rounded-b-2xl z-20" />

        {/* Status bar */}
        <div className="relative bg-[#075E54] pt-3 pb-1 px-5 flex items-center justify-between text-white text-[11px] font-medium">
          <span>9:41</span>
          <div className="flex items-center gap-1">
            <Signal className="w-3 h-3" />
            <Wifi className="w-3 h-3" />
            <BatteryFull className="w-3.5 h-3.5" />
          </div>
        </div>

        {/* WhatsApp chat header */}
        <div className="relative bg-[#075E54] px-4 py-3 flex items-center gap-3">
          <img
            src={avatarSrc}
            alt={parentName}
            loading="lazy"
            className="w-10 h-10 rounded-full object-cover ring-2 ring-white/20"
          />
          <div className="flex-1">
            <p className="text-white text-sm font-semibold leading-tight">{parentName}</p>
            <p className="text-white/60 text-[11px] leading-tight">via AYANA · online</p>
          </div>
        </div>

        {/* Chat body */}
        <div
          className="relative px-3 py-4 space-y-2.5 min-h-[460px]"
          style={{
            background:
              "repeating-linear-gradient(135deg, #0B141A, #0B141A 40px, #0E191F 40px, #0E191F 80px)",
          }}
        >
          {msgs.map((m, i) => {
            const isAyana = m.from === "ayana";
            return (
              <motion.div
                key={i}
                custom={i}
                initial="hidden"
                animate="show"
                variants={bubbleVariants}
                className={`flex flex-col ${isAyana ? "items-start" : "items-end"}`}
              >
                {/* Message bubble */}
                <div
                  className={`max-w-[82%] rounded-2xl px-3.5 py-2 text-[13px] leading-snug shadow ${
                    isAyana
                      ? "bg-[#1F2C34] text-white rounded-tl-sm"
                      : "bg-[#DCF8C6] text-[#111B21] rounded-tr-sm"
                  }`}
                >
                  {m.voice ? (
                    <span className="flex items-center gap-2 py-0.5">
                      <Mic className="w-3.5 h-3.5 shrink-0 text-ayana-bright" />
                      <span className="flex items-center gap-0.5">
                        {[3, 6, 4, 8, 5, 7, 3].map((h, idx) => (
                          <span
                            key={idx}
                            className="w-[2.5px] rounded-full bg-ayana-bright/70"
                            style={{ height: `${h * 2}px` }}
                          />
                        ))}
                      </span>
                      <span className="text-[10px] opacity-70">0:04</span>
                    </span>
                  ) : (
                    <span>{m.text}</span>
                  )}
                  <span
                    className={`flex items-center gap-1 justify-end mt-1 text-[10px] ${
                      isAyana ? "text-white/40" : "text-[#3A4A3F]/70"
                    }`}
                  >
                    {m.time}
                    {!isAyana && <CheckCheck className="w-3 h-3 text-[#53BDEB]" />}
                    {isAyana && <Check className="w-3 h-3" />}
                  </span>
                </div>

                {/* Quick-reply button pills — only on AYANA messages */}
                {isAyana && m.buttons && (
                  <motion.div
                    custom={i + 0.5}
                    initial="hidden"
                    animate="show"
                    variants={bubbleVariants}
                    className="mt-1.5 flex flex-wrap gap-1.5 max-w-[90%]"
                  >
                    {m.buttons.map((btn, bi) => (
                      <span
                        key={bi}
                        className="inline-block rounded-full border border-[#00A884]/70 bg-[#0B141A] text-[#00A884] text-[11px] font-medium px-2.5 py-1 leading-none"
                      >
                        {btn}
                      </span>
                    ))}
                  </motion.div>
                )}
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
