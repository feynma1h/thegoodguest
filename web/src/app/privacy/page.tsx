/**
 * Privacy Policy.
 *
 * DERIVED FROM CODE, NOT FROM A TEMPLATE. Every factual claim below traces to
 * something in this repo, and the trace is named in a comment beside it so a
 * future change to the pipeline shows up here as a stale comment rather than
 * as a quiet lie. If you change what a capture contains, where it is stored,
 * how long it lives, or what leaves to a third party, this file changes in
 * the same commit.
 *
 * OPERATOR REVIEW NOTES — resolve before publishing:
 *   1. FILLED 2026-08-08. Operator is Utkarsh Singh, an individual (not a
 *      company); contact is the operator's personal address. If an entity is
 *      later incorporated, §1 changes here AND in Terms §1, and Terms §12
 *      arguably makes that a material change requiring notice.
 *   1a. NO POSTAL ADDRESS IS PUBLISHED, deliberately. GDPR Art. 13(1)(a) and
 *      India's DPDP require the controller's identity and CONTACT DETAILS;
 *      the published email satisfies both. Germany's Impressum rule is the
 *      known exception — if the service acquires German users, a postal
 *      address must be added here and in Terms §1. Do not "restore" the
 *      address slot without that trigger; it would publish a home address.
 *   2. Confirm your processors' current terms say what §5 says they say —
 *      in particular that Anthropic's commercial API terms exclude API
 *      inputs/outputs from model training, and Google Cloud's DPA covers
 *      the buckets and Firestore. Both were true when this was written;
 *      neither is ours to promise on their behalf.
 *   3. Firestore's location is set at the project level; §4 states the
 *      compute and blob region, which is verified (asia-southeast1). If the
 *      Firestore database is in a different multi-region, say so there.
 *   4. If you add ANY per-user collection or prefix, it must appear both in
 *      services/api-public/account_deletion.py and in §7 here.
 */

import type { Metadata } from "next";

import LegalPage, { M, Section } from "@/components/LegalPage";

export const metadata: Metadata = {
  title: "Privacy Policy — The Good Guest",
  description:
    "What a room scan contains, where it goes, who processes it, how long it is kept, and how to delete all of it.",
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="8 August 2026"
      summary={
        <>
          You point a phone at a room and we turn it into a 3D model of that
          room. To do that we hold photographs of your home. This page says
          exactly what we collect, exactly where it goes, and exactly how to
          make all of it disappear — in the plainest terms we can manage,
          with the uncomfortable parts included.
        </>
      }
    >
      <Section n="1" title="Who this is about">
        <p>
          This policy covers The Good Guest iPhone capture app and the
          web app (together, “the service”). The service
          is operated by Utkarsh Singh (“we”), an individual.
        </p>
        <p>
          Questions, requests, and complaints: 23singhutkarsh@gmail.com.
        </p>
      </Section>

      {/* Source: packages/schemas/capture_bundle.proto */}
      <Section n="2" title="What a scan contains">
        <p>
          A scan (we call it a <em>capture</em>) is the raw material for
          everything else. One capture contains:
        </p>
        <ul className="ml-4 list-disc space-y-1.5 marker:text-ink/30">
          <li>
            <strong>Photographs of the room.</strong> The app keeps a still
            frame roughly every 10 cm or 5° of camera movement, so a walk
            around a room produces a few hundred JPEG images. These are
            ordinary photographs of your home and are the most sensitive thing
            we hold.
          </li>
          <li>
            <strong>Depth measurements</strong>, on iPhone Pro models with a
            LiDAR sensor: a <M>256×192</M> grid of distances, in metres,
            per frame, plus a per-pixel confidence value.
          </li>
          <li>
            <strong>Camera motion.</strong> Position and orientation for each
            frame, lens parameters, and the direction of gravity. These
            describe where the phone was inside the room, not where the room is
            in the world.
          </li>
          <li>
            <strong>Room geometry.</strong> Detected wall, floor, and ceiling
            planes, and — on Pro devices — Apple RoomPlan’s model of the
            room: wall outlines, a floor polygon, doors and windows, and boxes
            around furniture with categories and dimensions.
          </li>
          <li>
            <strong>Device and app facts.</strong> The device <em>model</em>{" "}
            string (e.g. <M>iPhone17,1</M>), iOS version, app version, whether
            the device has LiDAR, and a random identifier generated on first
            launch and stored in the iOS Keychain. That identifier is
            per-installation; it is not your Apple ID, your phone number, or
            any Apple-provided device ID.
          </li>
          <li>
            <strong>Times.</strong> When the capture started and ended.
          </li>
        </ul>
        <p>
          A capture does <strong>not</strong> contain your location. The app
          never requests location permission, and no GPS coordinates are read,
          stored, or transmitted. The camera positions in a capture are
          relative to wherever you happened to start scanning.
        </p>
        <p>
          The app does not record audio. There is no microphone use anywhere in
          the capture path.
        </p>
      </Section>

      {/* Source: iOS AuthManager + web lib/firebase.ts; decisions 0036/0051/0094 */}
      <Section n="3" title="Who you are to us">
        <p>
          The capture app signs you in <strong>anonymously</strong> on first
          launch. That produces an opaque account identifier and nothing else —
          no email, no name, no profile. You can use the app this way
          indefinitely.
        </p>
        <p>
          If you want to reach your rooms in a browser, you can attach Sign in
          with Apple to that same anonymous account, and then sign in on the
          web with Apple or with Google. Attaching a provider gives us whatever
          that provider releases to us — typically an email address, and a
          stable provider-specific identifier. With Apple you may choose to
          hide your email, in which case we receive only a relay address.
        </p>
        <p>
          Your account identifier does not change when you attach a provider.
          The web app can only ever sign you <em>in</em>; it will not create a
          new account, precisely so that a browser sign-in can never orphan the
          rooms on your phone.
        </p>
      </Section>

      {/* Source: infra/eventarc_setup.sh, infra/api-public.env.yaml, deploy scripts */}
      <Section n="4" title="Where it is stored">
        <p>
          Captures are uploaded from the phone directly to Google Cloud
          Storage. Processing runs on Google Cloud Run in the{" "}
          <M>asia-southeast1</M> (Singapore) region, and the buckets live in
          the same region. Records — your list of rooms, upload state, and
          conversations — are held in Google Cloud Firestore.
        </p>
        <p>
          If you are not in Singapore, this means your data is transferred and
          processed outside your country. By using the service you understand
          that this transfer takes place. Google Cloud is engaged as a
          processor under its standard data processing terms.
        </p>
      </Section>

      {/* Source: services/perception-obj/shell_material.py (0069/0089),
          services/api-public/{scene_facts,guest_prompt}.py (0058/0059/0096) */}
      <Section n="5" title="What leaves the system, and to whom">
        <p>
          Two things go to a third party beyond our cloud provider. Both go to{" "}
          <strong>Anthropic</strong>, and they send very different amounts of
          your room, so we describe them separately.
        </p>
        <p>
          <strong>a. Working out what your walls and floor are made of.</strong>{" "}
          To decide whether a floor reads as wood, tile, stone, carpet, or
          concrete, we send up to four small rectified crops of that surface —{" "}
          <strong>actual photographic image data from your room</strong> — to
          Anthropic’s API, and get back a one-word family and a
          confidence score. This happens at most once per surface per room, and
          the crops are close-ups of a wall or floor patch rather than views of
          the whole room. It is nonetheless the one place where pictures of
          your home are transmitted to a company that is not our cloud
          provider.
        </p>
        <p>
          <strong>b. The conversation about your room.</strong> When you talk to
          the guest on a room’s page, what we send is{" "}
          <strong>text, not pictures</strong>: a derived list of what was found
          in the room (“bed”, “desk”, “two
          chairs”), approximate distances and sizes, and the messages you
          type. No image, depth map, or coordinate ever enters that request.
        </p>
        <p>
          We do not sell your data, we do not share it with advertisers, and we
          do not authorise any processor to use your content to train models.
          Our processors handle it under their own published terms, which are
          theirs to change and yours to read.
        </p>
        <p>
          Other Google services in the path — Firebase Authentication for
          sign-in, and Firebase Cloud Messaging if you allow notifications — see
          only account identifiers and delivery tokens, never room content.
        </p>
        <p>
          Beyond this, we may disclose data if we are legally required to, or
          to protect the service or someone’s safety. If we are ever
          acquired, the data follows the service, and this policy follows it
          too until you are told otherwise.
        </p>
      </Section>

      {/* Source: infra/eventarc_setup.sh sections 2-5; infra/api-internal.env.yaml */}
      <Section n="6" title="How long it is kept">
        <ul className="ml-4 list-disc space-y-1.5 marker:text-ink/30">
          <li>
            <strong>The raw scan — every photograph and depth frame you
            uploaded — is deleted automatically 24 hours after upload.</strong>{" "}
            A storage lifecycle rule enforces this; it is not a policy we have
            to remember to apply. This is the single most important retention
            fact on this page.
          </li>
          <li>
            <strong>The room we build from it is kept until you delete it</strong>{" "}
            — the 3D model, the surfaces, the inventory of what was found. This
            is the product; it persists so that your house is there when you
            come back.
          </li>
          <li>
            <strong>Failed scans</strong> — captures that could not be processed
            — are removed 90 days after they fail.
          </li>
          <li>
            <strong>Upload bookkeeping</strong> expires 7 days after the upload.
          </li>
          <li>
            <strong>Intermediate processing files</strong> kept to avoid
            recomputing your room are deleted after 180 days.
          </li>
          <li>
            <strong>Conversations</strong> are kept with the room they belong
            to, and go when it goes.
          </li>
        </ul>
      </Section>

      {/* Source: services/api-public/account_deletion.py (decision 0095) */}
      <Section n="7" title="Deleting everything">
        <p>
          Open the account menu in the web app and choose{" "}
          <strong>Delete account</strong>. This is not a request queued for
          review; it runs immediately and removes:
        </p>
        <ul className="ml-4 list-disc space-y-1.5 marker:text-ink/30">
          <li>every room and everything built from it, in storage;</li>
          <li>any raw capture blobs still inside their 24-hour window;</li>
          <li>
            every record of yours — rooms, upload sessions, usage counters, and
            every conversation and message;
          </li>
          <li>the account itself, last.</li>
        </ul>
        <p>
          Deletion runs storage first and the account last, deliberately: if it
          were interrupted, nothing would be stranded without a record pointing
          at it, and you would still be able to sign in and run it again. It is
          safe to run twice.
        </p>
        <p>
          Deleting your account does not reach into your phone. The capture app
          will start over with a fresh anonymous account the next time you open
          it, and any captures still on the device are yours to delete by
          removing the app.
        </p>
        <p>
          To delete a single room rather than everything, or to ask what we
          hold about you, write to 23singhutkarsh@gmail.com. Depending on
          where you live you may have rights to access, correct, export, or
          restrict the processing of your data, and to complain to a data
          protection authority; we will honour those requests through that
          address.
        </p>
      </Section>

      {/* Source: services/perception-obj/privacy.py (decision 0089) */}
      <Section n="8" title="People in your scans">
        <p>
          If someone is in the room while you scan it, they will be
          photographed. This deserves a straight answer rather than a
          reassurance.
        </p>
        <p>
          What the system does: it looks for people in every frame and{" "}
          <strong>excludes them</strong> from the room it builds. A detected
          person is never reconstructed as an object, never named in the
          inventory, never used as evidence of what a wall or floor looks like,
          and is disqualified from the crops described in §5a. In testing, a
          third of one wall’s measured colour turned out to be a person
          standing in front of it; that measurement is now excluded.
        </p>
        <p>
          What we will not claim: that detection is perfect. It is a machine
          learning model, it will miss people, and the raw frames themselves
          always contain whoever was in the room until the 24-hour deletion
          in §6 removes them. Rooms processed before this behaviour shipped may
          still carry measurements taken from a person.
        </p>
        <p>
          So: ask people to step out before you scan. The app asks you to do
          this too. It is the only method here that works every time.
        </p>
        <p>
          If you scan a space that is not yours, or people who have not agreed
          to it, that is on you — see the Terms.
        </p>
      </Section>

      <Section n="9" title="Security">
        <p>
          Everything travels over TLS. Rooms are scoped to the account that
          made them, and a request for someone else’s room is refused
          rather than filtered. Links to your 3D files are individually signed
          and expire after an hour. The keys our services use are held in
          Google Secret Manager, and each service runs with only the
          permissions it actually needs.
        </p>
        <p>
          No system is immune. If we discover a breach affecting your data we
          will tell you and the relevant authority as required by law.
        </p>
      </Section>

      <Section n="10" title="What we do not do">
        <p>
          The web app contains no analytics, no tracking pixels, no advertising
          technology, and no third-party scripts of any kind. It sets no
          cookies for tracking. Two small flags are stored in your
          browser’s local storage — whether you have any rooms yet, and
          whether you have already watched a particular room assemble — so the
          first screen and the reveal behave sensibly. Neither is sent
          anywhere, and clearing site data removes both.
        </p>
      </Section>

      <Section n="11" title="Children">
        <p>
          The service is not directed at children under 13 (or the equivalent
          minimum age where you live), and we do not knowingly collect their
          data. If you believe a child has used the service, write to{" "}
          23singhutkarsh@gmail.com and we will delete the account.
        </p>
      </Section>

      <Section n="12" title="Changes">
        <p>
          If this policy changes in a way that materially affects what we
          collect or who receives it, we will say so in the app before the
          change takes effect. The date at the top always reflects the current
          version.
        </p>
      </Section>
    </LegalPage>
  );
}
