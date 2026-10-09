/// <reference types="node" />

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { DICTIONARIES } from './index'

function walk(dir: string, files: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) {
      walk(path, files)
    } else if (
      /\.(ts|tsx)$/.test(entry) &&
      !entry.endsWith('.test.ts') &&
      !entry.endsWith('.test.tsx')
    ) {
      files.push(path)
    }
  }
  return files
}

describe('locale dictionaries', () => {
  it('keeps English and Persian key sets identical', () => {
    const enKeys = new Set(Object.keys(DICTIONARIES.en))
    const faKeys = new Set(Object.keys(DICTIONARIES.fa))
    expect([...faKeys].filter((key) => !enKeys.has(key)).sort()).toEqual([])
    expect([...enKeys].filter((key) => !faKeys.has(key)).sort()).toEqual([])
  })

  it('has no empty translations', () => {
    const empty = [...Object.entries(DICTIONARIES.en), ...Object.entries(DICTIONARIES.fa)]
      .filter(([, value]) => !value.trim())
      .map(([key]) => key)
    expect(empty).toEqual([])
  })

  it('keeps {placeholder} sets identical across locales', () => {
    const placeholders = (value: string) =>
      [...value.matchAll(/\{(\w+)\}/g)]
        .map((match) => match[1])
        .sort()
        .join(',')
    const mismatches = Object.keys(DICTIONARIES.en).filter(
      (key) => placeholders(DICTIONARIES.en[key]) !== placeholders(DICTIONARIES.fa[key] ?? ''),
    )
    expect(mismatches).toEqual([])
  })

  it('defines every literal key used in t() calls', () => {
    const srcRoot = resolve(process.cwd(), 'src')
    const pattern = /(?:^|[^\w$.])t\(\s*['"]([^'"]+)['"]/g
    const missing = new Set<string>()
    for (const file of walk(srcRoot)) {
      const content = readFileSync(file, 'utf8')
      for (const match of content.matchAll(pattern)) {
        if (!(match[1] in DICTIONARIES.en)) missing.add(match[1])
      }
    }
    expect([...missing].sort()).toEqual([])
  })
})
