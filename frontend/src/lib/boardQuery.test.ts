import { describe, expect, it } from 'vitest'

import {
  ALL_TASK_TYPES,
  boardIssueTypes,
  boardVisibleStatuses,
  buildBoardQuery,
} from './boardQuery'
import type { WorkflowStatusRead } from './types'

const PROJECT = '11111111-1111-1111-1111-111111111111'
const SPRINT = '22222222-2222-2222-2222-222222222222'

const workflow: WorkflowStatusRead[] = [
  {
    id: null,
    key: 'new',
    name: 'New',
    category: 'todo',
    wip_limit: null,
    transitions: ['doing'],
    position: 1,
  },
  {
    id: null,
    key: 'todo',
    name: 'To do',
    category: 'todo',
    wip_limit: null,
    transitions: ['doing'],
    position: 0,
  },
  {
    id: null,
    key: 'doing',
    name: 'Doing',
    category: 'in_progress',
    wip_limit: null,
    transitions: [],
    position: 2,
  },
]

describe('boardVisibleStatuses', () => {
  it('returns every status by workflow position when no subset is saved', () => {
    expect(boardVisibleStatuses(workflow, null).map((s) => s.key)).toEqual([
      'todo',
      'new',
      'doing',
    ])
    expect(
      boardVisibleStatuses(workflow, {
        filter_query: null,
        columns: null,
        issue_types: null,
      }).map((s) => s.key),
    ).toEqual(['todo', 'new', 'doing'])
  })

  it('keeps only the saved column subset, in workflow order', () => {
    expect(
      boardVisibleStatuses(workflow, {
        filter_query: null,
        columns: ['doing', 'todo'],
        issue_types: null,
      }).map((s) => s.key),
    ).toEqual(['todo', 'doing'])
  })

  it('ignores unknown keys in a stale subset', () => {
    expect(
      boardVisibleStatuses(workflow, {
        filter_query: null,
        columns: ['doing', 'removed_status'],
        issue_types: null,
      }).map((s) => s.key),
    ).toEqual(['doing'])
  })
})

describe('boardIssueTypes', () => {
  it('defaults to every issue type', () => {
    expect(boardIssueTypes(null)).toEqual(ALL_TASK_TYPES)
    expect(
      boardIssueTypes({ filter_query: null, columns: null, issue_types: [] }),
    ).toEqual(ALL_TASK_TYPES)
  })

  it('returns the saved subset', () => {
    expect(
      boardIssueTypes({
        filter_query: null,
        columns: null,
        issue_types: ['story', 'task'],
      }),
    ).toEqual(['story', 'task'])
  })
})

describe('buildBoardQuery', () => {
  const emptyBoard = { filter_query: null, columns: null, issue_types: null }

  it('always scopes the query to the project', () => {
    expect(buildBoardQuery({ projectId: PROJECT, board: emptyBoard })).toBe(
      `project = ${PROJECT}`,
    )
  })

  it('adds issue type and column subsets', () => {
    expect(
      buildBoardQuery({
        projectId: PROJECT,
        board: {
          filter_query: null,
          columns: ['todo', 'doing'],
          issue_types: ['story', 'task'],
        },
      }),
    ).toBe(
      `project = ${PROJECT} AND type in (story, task) AND status in (todo, doing)`,
    )
  })

  it('omits a type clause when every type is selected', () => {
    expect(
      buildBoardQuery({
        projectId: PROJECT,
        board: { filter_query: null, columns: null, issue_types: [...ALL_TASK_TYPES] },
      }),
    ).toBe(`project = ${PROJECT}`)
  })

  it('maps the sprint selector', () => {
    expect(
      buildBoardQuery({ projectId: PROJECT, board: emptyBoard, sprintFilter: SPRINT }),
    ).toBe(`project = ${PROJECT} AND sprint = ${SPRINT}`)
    expect(
      buildBoardQuery({
        projectId: PROJECT,
        board: emptyBoard,
        sprintFilter: '__backlog__',
      }),
    ).toBe(`project = ${PROJECT} AND sprint is empty`)
  })

  it('appends the advanced TeamQL filter last', () => {
    expect(
      buildBoardQuery({
        projectId: PROJECT,
        board: {
          filter_query: 'priority = high AND label = bug',
          columns: null,
          issue_types: ['task'],
        },
      }),
    ).toBe(
      `project = ${PROJECT} AND type in (task) AND priority = high AND label = bug`,
    )
  })
})
