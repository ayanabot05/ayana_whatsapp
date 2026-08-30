import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { Link } from "react-router-dom";
import { ArrowLeft, Mail } from "lucide-react";

const SUPPORT_EMAIL = "admin@ayanabott.com";

function LegalShell({ title, updated, children }) {
  return (
    <div className="min-h-screen bg-ayana-bg flex flex-col">
      <Navbar />
      <main className="flex-1 max-w-3xl mx-auto px-5 sm:px-8 py-10 w-full">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-ayana-secondary hover:text-ayana-text transition-colors mb-8">
          <ArrowLeft className="w-4 h-4" /> Back to home
        </Link>
        <h1 className="font-display text-3xl sm:text-4xl font-semibold text-ayana-text">{title}</h1>
        <p className="mt-2 text-sm text-ayana-muted">Last updated: {updated}</p>
        <div className="mt-8 space-y-6 text-ayana-secondary leading-relaxed">{children}</div>
      </main>
      <Footer />
    </div>
  );
}

const H = ({ children }) => <h2 className="font-display text-xl font-medium text-ayana-text mt-8">{children}</h2>;

export function Privacy() {
  return (
    <LegalShell title="Privacy Policy" updated="August 2026">
      <p>AYANA exists to help you stay close to your parents. We treat your family's data with the care it deserves. This policy explains what we collect, who helps us process it, and how you stay in control.</p>

      <H>Who this covers</H>
      <p>Two kinds of people use AYANA: the <span className="text-ayana-text font-medium">child</span> who creates an account and configures care, and the <span className="text-ayana-text font-medium">parent</span> who receives and replies to check-ins on WhatsApp. Messages are always sent under the child's name — AYANA never pretends to be a person, and never hides who set the check-ins up.</p>

      <H>What we collect</H>
      <p>
        <span className="text-ayana-text font-medium">From you:</span> your name, phone number, city, and timezone, verified via a one-time SMS code.
      </p>
      <p>
        <span className="text-ayana-text font-medium">About your parent:</span> their name, relationship to you, WhatsApp number, preferred name or nicknames, language, timezone, city, notes you add, a medicine list and reminder times if you set them up, and any daily habits you choose to track.
      </p>
      <p>
        <span className="text-ayana-text font-medium">From your care setup:</span> your chosen check-in schedule, your plan tier and its limits, consent records for both you and your parent, and delivery logs for messages sent.
      </p>
      <p>
        <span className="text-ayana-text font-medium">From conversations:</span> your parent's WhatsApp replies — text and voice — including wellness signals like mood or medicine confirmations that we surface to you as care summaries, and keyword-based checks that help flag possible urgent situations.
      </p>

      <H>Who helps us process it</H>
      <p>We rely on a small set of specialized providers, each handling only what they need to do their job:</p>
      <ul className="list-disc list-inside space-y-1.5">
        <li>Meta's WhatsApp Business Platform — delivers and receives your parent's WhatsApp messages.</li>
        <li>Supabase — hosts our sign-in system and core database.</li>
        <li>Sarvam AI — powers speech-to-text, text-to-speech, and translation for regional-language check-ins.</li>
        <li>Google Gemini — helps understand check-in replies and extract wellness summaries.</li>
        <li>Our payment processor — handles billing if you're on a paid plan; we don't store full card details ourselves.</li>
      </ul>
      <p>None of these providers use your family's data for their own advertising, and we don't sell data to anyone.</p>

      <H>How we use it</H>
      <p>Solely to deliver the scheduled care check-ins you configure, generate the wellness summaries and reports on your dashboard, and — where the escalation chain you set up is triggered — reach out to your listed emergency contacts.</p>

      <H>Consent</H>
      <p>We record explicit consent for both your setup and your parent's participation. By adding a parent, you confirm they're aware of and welcome these messages.</p>

      <H>Data retention</H>
      <p>We keep check-in history and wellness data for as long as your account is active, so trends stay useful over time. Deleting your account removes it — see "Your rights" below.</p>

      <H>Security</H>
      <p>Secrets are stored server-side only. Passwords are hashed. Access to your data is protected by secure authentication and OTP verification. WhatsApp webhooks are signature-verified.</p>

      <H>Your rights</H>
      <p>You can edit or delete any profile or schedule at any time from your dashboard. You can permanently delete your account and associated data — see our <Link to="/data-deletion" className="text-ayana-primary underline">Data Deletion Instructions</Link> for how.</p>

      <H>Voice notes</H>
      <p>Voice replies from your parent are preserved in their original form and are not translated or altered, though we may transcribe them to generate your care summaries.</p>

      <H>Questions</H>
      <p>Reach us anytime at <a href={`mailto:${SUPPORT_EMAIL}`} className="text-ayana-primary underline">{SUPPORT_EMAIL}</a>.</p>
    </LegalShell>
  );
}

export function Terms() {
  return (
    <LegalShell title="Terms of Use" updated="August 2026">
      <p>By using AYANA you agree to these terms. Please read them with care.</p>

      <H>The service</H>
      <p>AYANA is a care companion that sends scheduled, warm WhatsApp messages to your parent in their chosen language, and surfaces their replies — including mood and wellness signals — back to you on your dashboard. It supports your care; it does not replace it.</p>

      <H>Your responsibilities</H>
      <p>You confirm you have your parent's consent to receive messages, and that the contact details you provide are accurate and yours to share. You're responsible for keeping your account credentials and OTP-verified phone number secure.</p>

      <H>Plans and limits</H>
      <p>AYANA offers tiered care plans (currently Nitya, Bandham, and Raksha), each with its own limits on the number of parents, daily check-ins, and medicine reminders you can set up. Your dashboard shows the exact limits for your current plan, and you can upgrade at any time to add more.</p>

      <H>Payments</H>
      <p>Paid plans are billed through our payment processor at checkout. During earlier testing phases access was offered free of charge — if you're on a free trial, your dashboard will say so; otherwise your selected plan's billing terms apply from checkout.</p>

      <H>Not an emergency service</H>
      <p>AYANA is not a medical, health, or emergency service. It may detect and flag urgent keywords in your parent's replies, but detection isn't guaranteed and nothing is monitored in real time by a human. You must not rely on it for emergencies. In a crisis, contact local emergency services immediately.</p>

      <H>Acceptable use</H>
      <p>You agree not to use AYANA to send unwanted, harmful, or unlawful messages to anyone, or to add a parent's number without their knowledge and consent.</p>

      <H>Changes</H>
      <p>We may update these terms as AYANA evolves. Continuing to use AYANA after a change means you accept the update.</p>

      <H>Questions</H>
      <p>Reach us anytime at <a href={`mailto:${SUPPORT_EMAIL}`} className="text-ayana-primary underline">{SUPPORT_EMAIL}</a>.</p>
    </LegalShell>
  );
}

export function Disclaimer() {
  return (
    <LegalShell title="Care Disclaimer" updated="August 2026">
      <p className="text-ayana-text font-medium">AYANA is a companion for connection, not a substitute for care, medical advice, or emergency response.</p>
      <H>Not medical advice</H>
      <p>Messages sent through AYANA — including medicine reminders and habit check-ins — are for emotional connection and gentle reminders only. They are not medical guidance and should not be treated as such.</p>
      <H>Emergency limitations</H>
      <p>AYANA can detect certain urgent keywords in replies and surface them to you, but it cannot guarantee detection and does not contact emergency services directly. If you or your parent face a medical or safety emergency, call local emergency services right away.</p>
      <H>Human care first</H>
      <p>Nothing here replaces your love, calls, and visits. AYANA simply helps carry a little warmth to your parents on the days in between.</p>
    </LegalShell>
  );
}

export function DataDeletion() {
  return (
    <LegalShell title="Data Deletion Instructions" updated="August 2026">
      <p>You can permanently delete your AYANA account and all associated data at any time, using either option below.</p>

      <H>Option 1 — Delete from your account</H>
      <ol className="list-decimal list-inside space-y-1.5">
        <li>Log in to your AYANA dashboard.</li>
        <li>Go to <span className="text-ayana-text font-medium">Settings → Account</span>.</li>
        <li>Select <span className="text-ayana-text font-medium">Delete Account</span>.</li>
        <li>Confirm the deletion request when prompted.</li>
      </ol>
      <p>Once confirmed, your account, your parents' profiles, check-in history, medicine and habit data, and stored conversation records are permanently deleted from our active systems within 30 days, except where we're required to retain limited records for legal or billing compliance.</p>

      <H>Option 2 — Email request</H>
      <p>
        If you can't access your dashboard, email us from the address linked to your account with the subject line "Data Deletion Request." Include the phone number(s) used for your account and any linked parent profiles so we can locate and remove the correct records. We'll confirm deletion by email within 30 days.
      </p>
      <a
        href={`mailto:${SUPPORT_EMAIL}?subject=Data%20Deletion%20Request`}
        className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-ayana-primary text-white font-medium hover:opacity-90 transition-opacity"
      >
        <Mail className="w-4 h-4" /> Email {SUPPORT_EMAIL}
      </a>

      <H>What happens to WhatsApp data</H>
      <p>
        Deleting your account stops all future WhatsApp check-in messages to your linked parent(s) and removes stored conversation history from our database. Message delivery records retained by Meta/WhatsApp itself are governed separately by{" "}
        <a href="https://www.whatsapp.com/legal/privacy-policy" target="_blank" rel="noopener noreferrer" className="text-ayana-primary underline">
          WhatsApp's own Privacy Policy
        </a>.
      </p>
    </LegalShell>
  );
}