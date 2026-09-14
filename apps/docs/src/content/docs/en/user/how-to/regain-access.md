---
title: Regain access
description: Request a new login code, receive a replacement invitation, or have an incorrect email fixed.
docId: DOC-P015
audience: [user]
diataxis: how-to
contentRevision: 1
reviewedRevision: 1
verifiedAgainst: 2043b72b7c5453b37978f2a58436243dbc378a00
reviewer: Björn Schotte
---

LeonAid uses magic links and six-digit one-time codes instead of passwords.

## Request a new login

1. Open `/login`.
2. Enter the exact **Login-E-Mail** to which you were invited and select
   **Login-Code anfordern**.
3. Open the most recent LeonAid email. Follow the magic link or enter its
   **Sechsstelliger Code**, then select **Anmelden**.

The request response is deliberately the same for unknown addresses. If no
message arrives, check the spelling and spam folder, then contact the relevant
charity or system administrator. After **Zu viele Versuche**, wait ten minutes.

## Receive a replacement invitation

An expired, revoked, or already-used invitation is not reactivated. Ask the
responsible administrator to resend it in a controlled way or correct the
address. Then open `/invite`, enter the invited email and newest code, and
select **Einladung bestätigen**.

## Correct an incorrect login email

Members cannot change their address themselves. A system administrator starts
the change after a fresh login. The previous address stays active until the new
address confirms the change. Confirmation revokes the affected account's
sessions; sign in again with the new address.
