/**
 * Terms of Service.
 *
 * Like the privacy policy, derived from what the system actually does. The
 * accuracy section (§7) is the one that matters most and the one most likely
 * to drift: it describes real, measured limitations of the reconstruction
 * pipeline, and it should be re-read whenever those limitations change.
 *
 * OPERATOR REVIEW NOTES — resolve before publishing:
 *   1. FILLED 2026-08-08. Operator is Utkarsh Singh, an individual (not a
 *      company); governing law India, forum Kanpur; liability cap ₹10,000.
 *      No postal address is published — see the matching note in
 *      app/privacy/page.tsx for the reasoning and the one trigger (German
 *      users) that would require adding one.
 *   1a. THE CAP IS THE WHOLE CLAUSE WHILE THE SERVICE IS FREE. §11 reads
 *      "the greater of the amount you paid us ... or ₹10,000", and there is
 *      no payment path in the codebase, so the first limb is always zero.
 *      If the service starts charging, re-read §11 — it stops being nominal.
 *   2. §13 is the Apple App Store rider. Apple requires either its standard
 *      EULA or a custom one containing at least these terms; keep the
 *      third-party-beneficiary clause if you ship a custom EULA.
 *   3. STILL OWED: have an Indian lawyer read §9-§11 before launch. Now that
 *      the forum is fixed, this is specific rather than general — India's
 *      Consumer Protection Act 2019 s.2(46) defines an "unfair contract" to
 *      include terms imposing unreasonable limits on liability, which is
 *      exactly what §11 is. Filling the cap in did not settle whether it is
 *      enforceable against an Indian consumer. Nothing here is legal advice.
 */

import type { Metadata } from "next";

import LegalPage, { M, Section } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Terms of Service — The Good Guest",
  description:
    "The agreement covering The Good Guest capture app and web app: what you may scan, what we promise, and what we do not.",
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      updated="8 August 2026"
      summary={
        <>
          Scan rooms you have the right to scan. What we build is an
          interpretation, not a survey — do not cut wood to it. Everything
          you capture stays yours, and you can delete all of it at any time.
          The rest is detail.
        </>
      }
    >
      <Section n="1" title="The agreement">
        <p>
          These terms are between you and Utkarsh Singh (“we”), an
          individual, and they
          govern your use of The Good Guest iPhone app and web app
          (“the service”). Using the service means you accept them.
          If you do not, do not use it.
        </p>
        <p>
          Our{" "}
          <a href="/privacy" className="text-accent hover:text-accent-deep">
            Privacy Policy
          </a>{" "}
          is part of this agreement and describes what we do with your data.
        </p>
      </Section>

      <Section n="2" title="What the service is, and what state it is in">
        <p>
          You scan a room with an iPhone; we reconstruct it as a 3D model you
          can look at and talk about.
        </p>
        <p>
          The service is early. Features appear, change, and are withdrawn.
          Reconstruction quality varies with your device, your room, and how
          you scan it. Treat it as something being built rather than something
          finished, because that is what it is.
        </p>
      </Section>

      <Section n="3" title="Your account">
        <p>
          The capture app creates an anonymous account for you automatically.
          You may attach Sign in with Apple to it, and afterwards sign in on the
          web with Apple or Google. You are responsible for what happens under
          your account and for keeping access to the provider you attached.
        </p>
        <p>
          You must be old enough to form a binding contract where you live, and
          at least 13.
        </p>
        <p>
          You can delete your account, and everything in it, from the account
          menu in the web app at any time. That is described in §7 of the
          Privacy Policy and it is immediate.
        </p>
      </Section>

      <Section n="4" title="What you may scan">
        <p>This is the obligation we most need you to take seriously.</p>
        <p>
          Only scan a space you own, occupy, or have permission to scan. Do not
          scan someone’s home without their agreement, and do not scan
          spaces where people have a reasonable expectation of privacy —
          bathrooms, changing rooms, hospital rooms, or anywhere similar.
        </p>
        <p>
          If a person will be in frame, get their agreement first. Better: ask
          them to step out. The system tries to exclude people from what it
          builds, and it is not guaranteed to succeed — see §8 of the Privacy
          Policy for exactly how far that protection goes.
        </p>
        <p>
          You confirm that you have every right and permission needed for each
          capture you upload, and you accept responsibility if you did not.
        </p>
      </Section>

      <Section n="5" title="Who owns what">
        <p>
          <strong>Your captures and your rooms are yours.</strong> We claim no
          ownership of them.
        </p>
        <p>
          To run the service we need permission to do the obvious things: store
          your capture, process it, send the small surface crops described in
          §5a of the Privacy Policy to our material-inference provider, build
          and host your room, and show it back to you. You grant us a
          worldwide, royalty-free licence to do exactly that and nothing more.
          It lasts as long as you keep the room and ends when you delete it.
        </p>
        <p>
          We will not use your rooms in marketing, publish them, or show them to
          anyone else without asking you first.
        </p>
        <p>
          The software, models, designs, and everything else that makes up the
          service remain ours.
        </p>
      </Section>

      <Section n="6" title="Fair use and limits">
        <p>
          Reconstruction runs on GPUs and costs real money per room, so
          accounts carry daily limits — currently around a dozen captures a
          day, and a bounded number of conversation turns per room per day.
          These are set to sit far above ordinary use; if you hit one, the app
          tells you when it resets. We may adjust them.
        </p>
        <p>Do not:</p>
        <ul className="ml-4 list-disc space-y-1.5 marker:text-ink/30">
          <li>
            work around limits, quotas, or authentication, or access rooms that
            are not yours;
          </li>
          <li>
            upload anything unlawful, or content you have no right to upload;
          </li>
          <li>
            probe, scrape, overload, or reverse-engineer the service, or use it
            to build a competing dataset;
          </li>
          <li>
            use it to harass, surveil, or profile anyone, or to case a property.
          </li>
        </ul>
      </Section>

      <Section n="7" title="Accuracy — please read this one">
        <p>
          What we give you back is a machine’s interpretation of
          photographs. It is frequently good and it is regularly wrong, in ways
          we can describe because we measure them:
        </p>
        <ul className="ml-4 list-disc space-y-1.5 marker:text-ink/30">
          <li>
            <strong>Dimensions are estimates.</strong> Where we state a size we
            state one number, hedged (“about 2.2 m at its
            longest”), because the underlying measurement does not
            reliably distinguish a length from a height. Gaps between objects
            are given as lower bounds — “at least” — never as exact
            clearances.
          </li>
          <li>
            <strong>Objects get misidentified.</strong> A wardrobe has been
            confidently reported as a refrigerator. Where the system is unsure
            it declines to name a thing at all, which is a feature, not an
            omission.
          </li>
          <li>
            <strong>Placement and orientation can be wrong</strong>, especially
            for thin, reflective, or fabric objects, and for anything only seen
            once. Mirrors in particular confuse depth sensing.
          </li>
          <li>
            <strong>Some things are missing.</strong> An object the system
            cannot place is left out rather than guessed at.
          </li>
        </ul>
        <p>
          <strong>
            Do not rely on anything the service tells you for a decision where
            being wrong has a cost.
          </strong>{" "}
          Do not buy furniture against it, cut material to it, plan
          construction or renovation from it, or use it in place of a
          professional survey. Measure the real room. The service is for
          exploring possibilities, not for committing to them.
        </p>
        <p>
          The conversational guest is a language model. It can be confidently
          incorrect. It is not advice of any kind — professional, structural,
          financial, or otherwise.
        </p>
      </Section>

      <Section n="8" title="Keeping your own copies">
        <p>
          We run automatic deletion on the raw scans after 24 hours (Privacy
          Policy §6) and we do not operate a backup service on your behalf. If a
          room matters to you, do not treat us as its only home. We may lose
          data, and this agreement does not make us liable for that beyond §11.
        </p>
      </Section>

      <Section n="9" title="No warranty">
        <p>
          The service is provided <M>“as is”</M> and{" "}
          <M>“as available”</M>, without warranties of any kind,
          express or implied, including merchantability, fitness for a
          particular purpose, accuracy, and non-infringement. We do not promise
          it will be uninterrupted, error-free, or that any result will be
          correct.
        </p>
        <p>
          Some jurisdictions do not allow these exclusions. Where that is so,
          they do not apply to you and your statutory rights are unaffected.
        </p>
      </Section>

      <Section n="10" title="Suspension and termination">
        <p>
          You may stop at any time by deleting your account. We may suspend or
          terminate access if you breach these terms, if we are required to, or
          if continuing would put the service or other people at risk. We will
          give you notice where we reasonably can.
        </p>
        <p>
          We may also discontinue the service. If we do, we will give
          reasonable notice and a window to retrieve your rooms.
        </p>
      </Section>

      <Section n="11" title="Liability">
        <p>
          To the fullest extent the law allows, we are not liable for indirect,
          incidental, special, consequential, or punitive damages, or for lost
          data, lost profits, or the cost of substitute services.
        </p>
        <p>
          Our total liability for any claim relating to the service is limited
          to the greater of the amount you paid us in the twelve months before
          the claim, or ₹10,000.
        </p>
        <p>
          Nothing here limits liability that cannot be limited by law —
          including for death or personal injury caused by negligence, or for
          fraud.
        </p>
      </Section>

      <Section n="12" title="Changes to these terms">
        <p>
          We may update these terms. For material changes we will give notice in
          the app before they take effect. Continuing to use the service after
          that means you accept the new version; if you do not, delete your
          account.
        </p>
      </Section>

      <Section n="13" title="If you got the app from Apple">
        <p>
          This agreement is between you and us, not with Apple, and Apple is not
          responsible for the app or its content. Apple has no obligation to
          provide support or maintenance for it.
        </p>
        <p>
          If the app fails to conform to any warranty, you may notify Apple and
          Apple will refund the purchase price, if any; to the maximum extent
          permitted by law, Apple has no other warranty obligation. We — not
          Apple — are responsible for addressing any claim relating to the app,
          including product liability, failure to conform to legal
          requirements, and consumer-protection claims, and for any third-party
          claim that the app infringes intellectual property rights.
        </p>
        <p>
          You confirm you are not located in a country subject to a U.S.
          Government embargo or designated as terrorist-supporting, and that you
          are not on any U.S. Government list of prohibited or restricted
          parties. Apple and its subsidiaries are third-party beneficiaries of
          this agreement and may enforce it against you.
        </p>
      </Section>

      <Section n="14" title="Law and disputes">
        <p>
          These terms are governed by the laws of India, and the courts at
          Kanpur, Uttar Pradesh have exclusive jurisdiction — except
          that if you are a consumer, you keep the protection of the mandatory
          laws of the country you live in, and may bring proceedings there.
        </p>
        <p>
          If any part of these terms is unenforceable, the rest stands. Our not
          enforcing something is not a waiver of it.
        </p>
        <p>
          Contact: 23singhutkarsh@gmail.com.
        </p>
      </Section>
    </LegalPage>
  );
}
