# J71b transient input status recovery

## Observation (2026-11-04)

On an installed apple-16k 7.3.0-rc1 J71b, a USB-C wall adapter remained
identified as BrickID 2.4 A, but the input limit fell to 500 mA. With the
panel off, net pack current alternated between a small charge and discharge.
The pack was about 86%, 25 C and 4.11 V; health reported Good.

Rebinding `apple-tristar-charger` restored the normal source-identification
and ramp sequence, but the limit fell again after seconds to about a minute.
A private trace instance recorded only existing regmap accesses to the known
charger status and input-limit registers, without initiating register reads
or writes. The status changed from 0x42 to 0x62 and back to 0x42 in about
104 ms. The driver's poll wrote the 500 mA fallback on 0x62, then continued
reading 0x42 while retaining the fallback. No source epoch change was logged.
The input limit had previously ramped through 1000, 1500, 2000 and 2400 mA.

This identifies a missing recovery path in the software. It does not establish
what bit 0x20 means or why the hardware reported it. The patch must retain the
strict ready-status check rather than mask that bit or force a current limit.

## Candidate

Patch 0019 remembers a non-ready input. Once the input is ready, it restarts
source identification rather than resuming the cached current allowance. The
previous USB allowance is invalidated while its data-session marker is kept.
Identification, the board maximum, battery checks and the normal ramp still
apply. A latched fault remains latched, and repeated non-ready polls do not
repeatedly restart attachment.

The change is in the shared Tristar driver: other boards using that driver
also need validation. Device-side testing of the candidate kernel is pending;
only the old-kernel failure and temporary rebind recovery have been observed.
The compiled C regression tests exercise the actual added helper with the
42/62/42 sequence, persistent non-ready input, a ramp in progress, latched
faults, first attachment, a lower existing limit, USB grant invalidation and
epoch wraparound.

The curated CHANGELOG is unchanged. Proposed Unreleased entry: recover source
identification after a transient Tristar input status instead of remaining at
the fallback input limit.
