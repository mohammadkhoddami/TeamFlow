import type { Dictionary, Locale } from './types'

import adminEn from './en/admin'
import authEn from './en/auth'
import commonEn from './en/common'
import layoutEn from './en/layout'
import projectsEn from './en/projects'
import settingsEn from './en/settings'
import taskExtrasEn from './en/taskExtras'
import tasksEn from './en/tasks'
import workEn from './en/work'

import adminFa from './fa/admin'
import authFa from './fa/auth'
import commonFa from './fa/common'
import layoutFa from './fa/layout'
import projectsFa from './fa/projects'
import settingsFa from './fa/settings'
import taskExtrasFa from './fa/taskExtras'
import tasksFa from './fa/tasks'
import workFa from './fa/work'

export const DICTIONARIES: Record<Locale, Dictionary> = {
  en: {
    ...commonEn,
    ...layoutEn,
    ...authEn,
    ...projectsEn,
    ...tasksEn,
    ...taskExtrasEn,
    ...workEn,
    ...adminEn,
    ...settingsEn,
  },
  fa: {
    ...commonFa,
    ...layoutFa,
    ...authFa,
    ...projectsFa,
    ...tasksFa,
    ...taskExtrasFa,
    ...workFa,
    ...adminFa,
    ...settingsFa,
  },
}

export type { Dictionary, Locale }
