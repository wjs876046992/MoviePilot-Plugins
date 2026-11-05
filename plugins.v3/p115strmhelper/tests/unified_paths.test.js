import test from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizePath,
  normalizePathJoin,
  getPathKey,
  getMpKey,
  usePathManagement,
} from '../src/components/composables/usePathManagement.js';

test('normalizePath cleans slashes and whitespace', () => {
  assert.equal(normalizePath(''), '');
  assert.equal(normalizePath(null), '');
  assert.equal(normalizePath('  /vol1/strm/TV/  '), '/vol1/strm/TV');
  assert.equal(normalizePath('\\vol1\\strm\\TV\\'), '/vol1/strm/TV');
  assert.equal(normalizePath('//vol1///strm//TV///'), '/vol1/strm/TV');
  assert.equal(normalizePath('/'), '/');
});

test('normalizePathJoin joins prefix without double slashes', () => {
  assert.equal(normalizePathJoin('/115open', '/TV/Show'), '/115open/TV/Show');
  assert.equal(normalizePathJoin('/115open/', 'TV/Show/'), '/115open/TV/Show');
  assert.equal(normalizePathJoin('', 'TV'), 'TV');
  assert.equal(normalizePathJoin('/115open', ''), '/115open');
});

test('reconcileUnifiedPaths merges symmetrical paths into 1 row with all scenes enabled', () => {
  const config = {
    transfer_monitor_paths: '/media/strm/Movie#/115/Movie',
    full_sync_strm_paths: '/media/strm/Movie#/115/Movie#1',
    increment_sync_strm_paths: '/media/strm/Movie#/115/Movie',
    monitor_life_paths: '/media/strm/Movie#/115/Movie',
    transfer_mp_mediaserver_paths: '',
    increment_sync_mp_mediaserver_paths: '',
    monitor_life_mp_mediaserver_paths: '',
    api_strm_mp_mediaserver_paths: '',
  };

  const pathMgmt = usePathManagement(config);
  pathMgmt.reconcileUnifiedPaths();

  assert.equal(pathMgmt.unifiedPaths.value.length, 1);
  const row = pathMgmt.unifiedPaths.value[0];
  assert.equal(row.local, '/media/strm/Movie');
  assert.equal(row.remote, '/115/Movie');
  assert.equal(row.enable_transfer, true);
  assert.equal(row.enable_full, true);
  assert.equal(row.enable_inc, true);
  assert.equal(row.enable_life, true);
});

test('reconcileUnifiedPaths merges asymmetrical paths losslessly', () => {
  // TV under CD2 is /115open/115/TV with prefix /115open, pure remote is /115/TV
  const config = {
    transfer_monitor_paths: '/media/strm/TV#/115open/115/TV#/115open',
    full_sync_strm_paths: '/media/strm/TV#/115/TV#1\n/media/strm/Anime#/115/Anime#0',
    increment_sync_strm_paths: '/media/strm/Movie#/115/Movie',
    monitor_life_paths: '',
    transfer_mp_mediaserver_paths: '/emby/strm#/mnt/strm',
    increment_sync_mp_mediaserver_paths: '',
    monitor_life_mp_mediaserver_paths: '',
    api_strm_mp_mediaserver_paths: '',
  };

  const pathMgmt = usePathManagement(config);
  pathMgmt.reconcileUnifiedPaths();

  // Should have 3 unified rows: TV, Anime, Movie
  assert.equal(pathMgmt.unifiedPaths.value.length, 3);

  // Row 1: TV (has CD2 prefix /115open, transfer and full enabled, inc and life disabled)
  const tvRow = pathMgmt.unifiedPaths.value.find(p => p.remote === '/115/TV');
  assert.ok(tvRow, 'TV row should exist');
  assert.equal(tvRow.cd2Prefix, '/115open');
  assert.equal(tvRow.enable_transfer, true);
  assert.equal(tvRow.enable_full, true);
  assert.equal(tvRow.enable_inc, false);
  assert.equal(tvRow.enable_life, false);

  // Row 2: Anime (only in full, but with #0 disabled)
  const animeRow = pathMgmt.unifiedPaths.value.find(p => p.remote === '/115/Anime');
  assert.ok(animeRow, 'Anime row should exist');
  assert.equal(animeRow.enable_transfer, false);
  assert.equal(animeRow.enable_full, false);
  assert.equal(animeRow.enable_inc, false);
  assert.equal(animeRow.enable_life, false);

  // Row 3: Movie (only in increment)
  const movieRow = pathMgmt.unifiedPaths.value.find(p => p.remote === '/115/Movie');
  assert.ok(movieRow, 'Movie row should exist');
  assert.equal(movieRow.enable_transfer, false);
  assert.equal(movieRow.enable_full, false);
  assert.equal(movieRow.enable_inc, true);
  assert.equal(movieRow.enable_life, false);

  // MP MediaServer mapping merged
  assert.equal(pathMgmt.unifiedMpPaths.value.length, 1);
  assert.equal(pathMgmt.unifiedMpPaths.value[0].local, '/emby/strm');
  assert.equal(pathMgmt.unifiedMpPaths.value[0].remote, '/mnt/strm');
});

test('syncAllPathsToConfig serializes correctly back to legacy fields', () => {
  const config = {
    transfer_monitor_paths: '',
    full_sync_strm_paths: '',
    increment_sync_strm_paths: '',
    monitor_life_paths: '',
    transfer_mp_mediaserver_paths: '',
    increment_sync_mp_mediaserver_paths: '',
    monitor_life_mp_mediaserver_paths: '',
  };

  const pathMgmt = usePathManagement(config);
  pathMgmt.unifiedPaths.value = [
    {
      local: '/strm/TV',
      remote: '/115/TV',
      cd2Prefix: '/115open',
      enable_transfer: true,
      enable_full: true,
      enable_inc: true,
      enable_life: true,
    },
    {
      local: '/strm/Anime',
      remote: '/115/Anime',
      cd2Prefix: '',
      enable_transfer: false,
      enable_full: false, // full_sync should write #0
      enable_inc: false,
      enable_life: false,
    },
  ];
  pathMgmt.unifiedMpPaths.value = [
    { local: '/emby/strm', remote: '/mnt/strm' },
  ];

  pathMgmt.syncAllPathsToConfig();

  // transfer: only TV (enable_transfer = true), effective remote has /115open prefix
  assert.equal(config.transfer_monitor_paths, '/strm/TV#/115open/115/TV#/115open');

  // full: TV has #1, Anime has #0
  assert.equal(config.full_sync_strm_paths, '/strm/TV#/115/TV#1\n/strm/Anime#/115/Anime#0');

  // increment: only TV
  assert.equal(config.increment_sync_strm_paths, '/strm/TV#/115/TV');

  // life: only TV
  assert.equal(config.monitor_life_paths, '/strm/TV#/115/TV');

  // MP MediaServer: distributed to all scenes
  assert.equal(config.transfer_mp_mediaserver_paths, '/emby/strm#/mnt/strm');
  assert.equal(config.increment_sync_mp_mediaserver_paths, '/emby/strm#/mnt/strm');
  assert.equal(config.monitor_life_mp_mediaserver_paths, '/emby/strm#/mnt/strm');
});

test('syncAllPathsToConfig respects custom scene overrides', () => {
  const config = {
    transfer_monitor_paths: '',
    full_sync_strm_paths: '',
    increment_sync_strm_paths: '',
    monitor_life_paths: '',
  };

  const pathMgmt = usePathManagement(config);
  pathMgmt.unifiedPaths.value = [
    {
      local: '/strm/Default',
      remote: '/115/Default',
      cd2Prefix: '',
      enable_transfer: true,
      enable_full: true,
      enable_inc: true,
      enable_life: true,
    },
  ];

  // User enables custom paths for transfer
  pathMgmt.customTransferPaths.value = true;
  pathMgmt.transferPaths.value = [
    { local: '/custom/transfer', remote: '/custom/pan', cd2Prefix: '' },
  ];

  pathMgmt.syncAllPathsToConfig();

  // transfer should use custom transferPaths
  assert.equal(config.transfer_monitor_paths, '/custom/transfer#/custom/pan#');
  // full should still use unifiedPaths
  assert.equal(config.full_sync_strm_paths, '/strm/Default#/115/Default#1');
});
