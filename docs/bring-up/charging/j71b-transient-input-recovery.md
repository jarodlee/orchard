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
previous USB allowance is invalidated, and the normal attachment routine handles
USB data-line policy.
Identification, the board maximum, battery checks and the normal ramp still
apply. A latched fault remains latched, and repeated non-ready polls do not
repeatedly restart attachment.

The change is in the shared Tristar driver: other boards using that driver
also need validation. The installed-base candidate has booted on J71b;
the upstream-adapted candidate still needs its own device validation.
The compiled C regression tests exercise the actual added helper with the
42/62/42 sequence, persistent non-ready input, a ramp in progress, latched
faults, first attachment, a lower existing limit, USB grant invalidation and
epoch wraparound.

The curated CHANGELOG is unchanged. Proposed Unreleased entry: recover source
identification after a transient Tristar input status instead of remaining at
the fallback input limit.

## Installed-base hardware follow-up (2026-11-04)

The candidate built from `dc0b2c1` booted using an additional BLS entry.
The original kernel, entry, initrd and DTB were preserved. The candidate
image digest and running kernel notes matched. Host tests passed 449 tests;
the Linux container passed 449 tests with one environment skip.

Moving from the Mac to the wall adapter exposed another existing issue:
USB suspend/resume reports still represented a USB session. The driver logged
`USB host allows 2 mA`, selected SDP and kept 500 mA. One charger rebind
repeated the same result. The upstream USB-role changes in power patch 0016
and the matching device-tree/controller changes address this separate case;
the installed-base candidate does not include them.

For a temporary wall-charge-only diagnostic, USB gadget data was unbound
over Wi-Fi, with its prior binding recorded privately for restoration, then
the charger was rebound once. Source identification reported BrickID 2.4 A
and the normal driver ramp reached 2.4 A. In 24 samples over 120 seconds,
net pack current was approximately 1.06-1.23 A into the battery, health Good
and temperature about 25 C. Existing-access tracing saw only ready status
0x42 during this window: it did not reproduce the 0x62 transition, so
this does not yet prove the new transient recovery path on hardware.

USB data is temporarily disabled for that wall-charge diagnostic; Wi-Fi
remains available. This workaround is not an image default or a permanent
repair. It must be restored before expecting Linux USB data connectivity.
The next candidate combines the current upstream USB-role handling with
patch 0019 and its matching J71b DTB; it requires a new build and DFU test.

That second candidate, built from the upstream-adapted `70db4d4`, passed
521 Linux-container tests (one environment skip) and a standard Orchard
source build. The published tools asset failed its checksum, so the build
used the supported `ORCHARD_PUBLISHED=off` source path without bypassing
verification. Its J71b DTB includes the USB-role link. All baseline exported
symbol CRCs are still present and unchanged; the original module tree and
initrd were retained. A separate v2 kernel/DTB directory and BLS entry are
staged, preserving both previous entries. This v2 has not yet booted.
