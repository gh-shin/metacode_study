import assert from 'node:assert/strict'
import test from 'node:test'

import { useStore } from '../src/store.ts'

const searchResult = {
  interpretation: {
    keywords_en: [],
    keywords_ko: [],
    answer_type: 'photo',
    date_from: null,
    date_to: null,
    countries: [],
    cities: [],
    fallback: false,
  },
  groups: [],
  trip_summary: [],
  total: 0,
}

function resetStore() {
  useStore.setState({
    mode: 'browse',
    selectedDate: null,
    selectedPhotoId: null,
    cluster: null,
    cameraRequest: null,
    selectionSeq: 0,
    searchQuery: '',
    searchResult: null,
    searching: false,
    returnTo: null,
  })
}

test('openPhoto opens one-photo detail from browse', () => {
  resetStore()

  const state = useStore.getState()
  assert.equal(typeof state.openPhoto, 'function')

  state.openPhoto('photo-1')

  assert.equal(useStore.getState().mode, 'photoDetail')
  assert.equal(useStore.getState().selectedPhotoId, 'photo-1')
  assert.equal(useStore.getState().selectedDate, null)
  assert.equal(useStore.getState().selectionSeq, 1)
})

test('closePhoto returns to search when opened from search context', () => {
  resetStore()
  useStore.setState({ mode: 'search', searchResult })

  useStore.getState().openPhoto('photo-2')
  useStore.getState().closePhoto()

  assert.equal(useStore.getState().mode, 'search')
  assert.equal(useStore.getState().selectedPhotoId, null)
  assert.equal(useStore.getState().searchResult, searchResult)
})

test('flyTo keeps padding in the camera request', () => {
  resetStore()
  const padding = { top: 76, bottom: 420, left: 40, right: 40 }

  useStore.getState().flyTo([127, 37.5], 14, padding)

  assert.deepEqual(useStore.getState().cameraRequest, {
    type: 'flyTo',
    center: [127, 37.5],
    zoom: 14,
    padding,
    seq: 1,
  })
})
