import type { ProfileCount } from '@/lib/types'

/**
 * Build an honest empty-state message.
 *
 * The old message always said "Run Sync All from Accounts to pull data."
 * That is wrong advice whenever the operator is simply looking at the wrong
 * marketplace — it sends them off to run an hour-long sync that changes
 * nothing. Two people have now concluded the app was broken because of it.
 *
 * A restored localStorage selection can land you on a marketplace with zero
 * campaigns while the others are full, so this is the common case, not an
 * edge case.
 */
export function emptyDataMessage(opts: {
  entity: string                       // 'campaigns' | 'ad groups' | 'keywords'
  profileCounts: ProfileCount[]
  currentProfileId: string | null
  accountName?: string | null
}): { message: string; switchToProfileId: string | null } {
  const { entity, profileCounts, currentProfileId, accountName } = opts

  if (profileCounts.length === 0) {
    return {
      message: `No ${entity} found for ${accountName ?? 'this account'}.`,
      switchToProfileId: null,
    }
  }

  const withData = profileCounts
    .filter(p => p.campaigns > 0)
    .sort((a, b) => b.campaigns - a.campaigns)

  // Nothing anywhere — this is the genuine first-run case, and the only time
  // "run a sync" is the right advice.
  if (withData.length === 0) {
    return {
      message: `No ${entity} found in any marketplace. Run Sync All from Accounts to pull data.`,
      switchToProfileId: null,
    }
  }

  const others = withData.filter(p => p.profile_id !== currentProfileId)

  // Viewing a specific, empty marketplace while others have data.
  if (currentProfileId && others.length > 0) {
    const current = profileCounts.find(p => p.profile_id === currentProfileId)
    const where = others
      .map(p => `${p.country_code ?? 'unknown'} has ${p.campaigns}`)
      .join(', ')
    return {
      message: `${current?.country_code ?? 'This marketplace'} has no campaigns. ${where}.`,
      switchToProfileId: others[0].profile_id,
    }
  }

  // Data exists in the selected marketplace but this view is filtered empty.
  return {
    message: `No ${entity} match the current filters.`,
    switchToProfileId: null,
  }
}
