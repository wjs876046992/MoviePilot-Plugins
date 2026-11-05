import { ref, watch } from 'vue';

// ============================================================
// 纯函数与工具函数（便于单元测试与跨组件复用）
// ============================================================

/** 路径归一化：消除多余斜杠、反斜杠、尾部斜杠，保留根目录单个 / */
export const normalizePath = (p) => {
  if (!p || typeof p !== 'string') return '';
  let s = p.trim().replace(/\\/g, '/');
  s = s.replace(/\/+/g, '/');
  if (s.length > 1 && s.endsWith('/')) {
    s = s.slice(0, -1);
  }
  return s;
};

export const getPathKey = (local, remote) => {
  return `${normalizePath(local)}:::${normalizePath(remote)}`;
};

export const getMpKey = (local, remote) => {
  return `${normalizePath(local)}:::${normalizePath(remote)}`;
};

/** 规范化路径拼接，避免双斜杠，保留前缀的绝对路径（前导 /） */
export const normalizePathJoin = (prefix, rest) => {
  const a = (prefix || '').trim().replace(/\/+$/, '');
  const b = (rest || '').trim().replace(/^\/+/, '').replace(/\/+$/, '');
  if (!b) return a || '';
  return a ? `${a}/${b}` : b;
};

/**
 * 把换行分隔的 `local#remote[#extra]` 配置串解析成行数组。
 *
 * ⚠️ 必须与 `watch` 里的解析逻辑**逐字同源**：`reconcileUnifiedPaths` 直接读
 * `config.*` 字符串而不是读 refs，因为 refs 由异步 watcher 填充 —— 在
 * `loadConfig()` 里 `Object.assign` 之后同步调用本函数时，refs 还是初始的空
 * 数组，会把「已存在的真实配置」当成「没有配置」，再在保存时把它覆盖成空串。
 */
export const parseLegacyLines = (raw) => {
  if (!raw || typeof raw !== 'string') return [];
  return raw.split('\n').filter(line => line.trim());
};

/** 解析 `local#remote` 两段式（增量同步 / 生活事件 / mp_mediaserver） */
export const parsePairLines = (raw) =>
  parseLegacyLines(raw).map(line => {
    const parts = line.split('#');
    return { local: parts[0] || '', remote: parts[1] || '' };
  });

/** 解析 `local#remote#0|1` 三段式（全量同步） */
export const parseFullSyncLines = (raw) =>
  parseLegacyLines(raw).map(line => {
    const parts = line.split('#');
    // 无第三段（旧格式）或第三段非 '0' 时均为开启；仅第三段为 '0' 时为关闭
    const enabled = parts.length < 3 || parts[2].trim() !== '0';
    return { local: parts[0] || '', remote: parts[1] || '', enabled };
  });

/**
 * 解析 `local#remote#cd2Prefix` 三段式（监控MP整理）。
 * 第三段是 CD2 挂载前缀，需要从 remote 里剥离出来还原成「纯网盘路径」。
 */
export const parseTransferLines = (raw) =>
  parseLegacyLines(raw).map(line => {
    const parts = line.split('#');
    const local = parts[0] || '';
    const fullRemote = parts[1] || '';
    const prefix = parts[2]?.trim() || '';
    let remote = fullRemote;
    if (prefix) {
      const normPrefix = prefix.replace(/^\/+/, '').replace(/\/+$/, '');
      const normFull = fullRemote.replace(/^\/+/, '').replace(/\/+$/, '');
      if (normFull === normPrefix || normFull.startsWith(normPrefix + '/')) {
        const rest = normFull.slice(normPrefix.length);
        remote = (rest.startsWith('/') ? rest : '/' + rest) || '';
      }
    }
    return { local, remote, cd2Prefix: prefix };
  });

/**
 * 路径管理 Composable
 * 管理所有路径数组的状态、双向同步监听和增删操作
 * @param {object} config - 插件配置的 reactive 对象
 */
export function usePathManagement(config) {
  // 路径管理 refs
  const transferPaths = ref([{ local: '', remote: '', cd2Prefix: '' }]);
  const transferMpPaths = ref([{ local: '', remote: '' }]);
  const fullSyncPaths = ref([{ local: '', remote: '', enabled: true }]);
  const incrementSyncPaths = ref([{ local: '', remote: '' }]);
  const incrementSyncMPPaths = ref([{ local: '', remote: '' }]);
  const monitorLifePaths = ref([{ local: '', remote: '' }]);
  const monitorLifeMpPaths = ref([{ local: '', remote: '' }]);
  const apiStrmPaths = ref([{ local: '', remote: '' }]);
  const apiStrmMPPaths = ref([{ local: '', remote: '' }]);
  const panTransferPaths = ref([{ path: '' }]);
  const shareReceivePaths = ref([{ path: '' }]);
  const offlineDownloadPaths = ref([{ path: '' }]);
  const transferExcludePaths = ref([{ path: '' }]);
  const incrementSyncExcludePaths = ref([{ local: '', remote: '' }]);
  const monitorLifeExcludePaths = ref([{ path: '' }]);
  const directoryUploadPaths = ref([{ src: '', dest_remote: '', dest_local: '', dest_strm: '', delete: false }]);
  const syncDelLibraryPaths = ref([{ mediaserver: '', moviepilot: '', p115: '' }]);
  const fuseStrmTakeoverRules = ref([{ extensions: '', names: '', paths: '', _use_extensions: false, _use_names: false, _use_paths: false }]);

  // ============================================================
  // 统一媒体库路径映射（方案 A：无损双向融合）
  // ============================================================
  const unifiedPaths = ref([{
    local: '',
    remote: '',
    cd2Prefix: '',
    enable_transfer: true,
    enable_full: true,
    enable_inc: true,
    enable_life: true,
  }]);
  const unifiedMpPaths = ref([{ local: '', remote: '' }]);

  // 各场景独立自定义路径开关（高级逃生通道）
  const customTransferPaths = ref(false);
  const customFullSyncPaths = ref(false);
  const customIncrementSyncPaths = ref(false);
  const customMonitorLifePaths = ref(false);
  const customApiStrmPaths = ref(false);

  const generatePathsConfig = (paths, key) => {
    const configText = paths.map(p => {
      if (key === 'panTransfer') {
        return p.path?.trim();
      }
      if (key === 'fullSync') {
        return `${p.local?.trim()}#${p.remote?.trim()}#${p.enabled !== false ? '1' : '0'}`;
      }
      if (key === 'transfer') {
        const local = p.local?.trim() ?? '';
        const remote = p.remote?.trim() ?? '';
        const cd2 = (p.cd2Prefix || '').trim();
        const effectiveRemote = cd2 ? normalizePathJoin(cd2, remote) : remote;
        return `${local}#${effectiveRemote}#${cd2}`;
      }
      return `${p.local?.trim()}#${p.remote?.trim()}`;
    }).filter(p => {
      if (key === 'panTransfer') {
        return p && p !== '';
      }
      if (key === 'fullSync') {
        const parts = p.split('#');
        return parts.length >= 2 && (parts[0]?.trim() || parts[1]?.trim());
      }
      if (key === 'transfer') {
        const parts = p.split('#');
        return parts.length >= 2 && (parts[0]?.trim() || parts[1]?.trim());
      }
      return p !== '#' && p !== '';
    }).join('\n');

    return configText;
  };

  /**
   * 存量路径双向无损融合：将旧版各个独立场景的路径聚合成统一映射表
   *
   * ⚠️ **数据源必须是 `config.*` 字符串，不能是下面那些 refs。**
   * refs 由 `watch(..., { immediate: true })` 填充，而 Vue 的 watcher 是**异步**
   * 的：`loadConfig()` 里 `Object.assign(config, data)` 之后同步调用本函数时，
   * refs 还停留在初始的空数组。用 refs 做数据源会把「用户真实存在的配置」读成
   * 空，并在保存时反手把 `config.full_sync_strm_paths` 等字段覆盖成空串 ——
   * 即静默清空用户配置。直接解析字符串则与时序无关。
   */
  const reconcileUnifiedPaths = () => {
    const map = new Map();

    const ensureItem = (local, remote) => {
      const key = getPathKey(local, remote);
      if (!map.has(key)) {
        map.set(key, {
          local: (local || '').trim(),
          remote: (remote || '').trim(),
          cd2Prefix: '',
          enable_transfer: false,
          enable_full: false,
          enable_inc: false,
          enable_life: false,
        });
      }
      return map.get(key);
    };

    // 1. 监控MP整理 (transfer_monitor_paths)
    parseTransferLines(config.transfer_monitor_paths).forEach(p => {
      if (p.local?.trim() || p.remote?.trim()) {
        const item = ensureItem(p.local, p.remote);
        item.enable_transfer = true;
        if (p.cd2Prefix?.trim() && !item.cd2Prefix) {
          item.cd2Prefix = p.cd2Prefix.trim();
        }
      }
    });

    // 2. 全量同步 (full_sync_strm_paths)
    parseFullSyncLines(config.full_sync_strm_paths).forEach(p => {
      if (p.local?.trim() || p.remote?.trim()) {
        const item = ensureItem(p.local, p.remote);
        item.enable_full = p.enabled !== false;
      }
    });

    // 3. 增量同步 (increment_sync_strm_paths)
    parsePairLines(config.increment_sync_strm_paths).forEach(p => {
      if (p.local?.trim() || p.remote?.trim()) {
        const item = ensureItem(p.local, p.remote);
        item.enable_inc = true;
      }
    });

    // 4. 监控115生活事件 (monitor_life_paths)
    parsePairLines(config.monitor_life_paths).forEach(p => {
      if (p.local?.trim() || p.remote?.trim()) {
        const item = ensureItem(p.local, p.remote);
        item.enable_life = true;
      }
    });

    // 5. API STRM 生成配置 (api_strm_config)
    if (Array.isArray(config.api_strm_config)) {
      config.api_strm_config.forEach(p => {
        const l = p.local_path || p.local || '';
        const r = p.pan_path || p.remote || '';
        if (l.trim() || r.trim()) {
          ensureItem(l, r);
        }
      });
    }

    const merged = Array.from(map.values());
    if (merged.length === 0) {
      unifiedPaths.value = [{
        local: '',
        remote: '',
        cd2Prefix: '',
        enable_transfer: true,
        enable_full: true,
        enable_inc: true,
        enable_life: true,
      }];
    } else {
      unifiedPaths.value = merged;
    }

    // MP-MediaServer 转换路径合并（同样读 config 字符串，理由见上）
    const mpMap = new Map();
    const allMpSources = [
      ...parsePairLines(config.transfer_mp_mediaserver_paths),
      ...parsePairLines(config.increment_sync_mp_mediaserver_paths),
      ...parsePairLines(config.monitor_life_mp_mediaserver_paths),
      ...parsePairLines(config.api_strm_mp_mediaserver_paths),
    ];
    allMpSources.forEach(p => {
      if (p.local?.trim() || p.remote?.trim()) {
        const key = getMpKey(p.local, p.remote);
        if (!mpMap.has(key)) {
          mpMap.set(key, { local: (p.local || '').trim(), remote: (p.remote || '').trim() });
        }
      }
    });
    const mergedMp = Array.from(mpMap.values());
    unifiedMpPaths.value = mergedMp.length > 0 ? mergedMp : [{ local: '', remote: '' }];
  };

  /**
   * 将统一映射表按勾选场景拆解分发写回 legacy 对应配置字段
   */
  const syncAllPathsToConfig = () => {
    // 1. 监控MP整理 (transfer_monitor_paths)
    if (customTransferPaths.value) {
      config.transfer_monitor_paths = generatePathsConfig(transferPaths.value, 'transfer');
    } else {
      const list = unifiedPaths.value
        .filter(p => p.enable_transfer && (p.local?.trim() || p.remote?.trim()))
        .map(p => ({
          local: p.local?.trim() || '',
          remote: p.remote?.trim() || '',
          cd2Prefix: (p.cd2Prefix || '').trim(),
        }));
      config.transfer_monitor_paths = generatePathsConfig(list, 'transfer');
      if (list.length > 0) {
        transferPaths.value = list;
      }
    }

    // 2. 全量同步 (full_sync_strm_paths)
    if (customFullSyncPaths.value) {
      config.full_sync_strm_paths = generatePathsConfig(fullSyncPaths.value, 'fullSync');
    } else {
      const list = unifiedPaths.value
        .filter(p => p.local?.trim() || p.remote?.trim())
        .map(p => ({
          local: p.local?.trim() || '',
          remote: p.remote?.trim() || '',
          enabled: !!p.enable_full,
        }));
      config.full_sync_strm_paths = generatePathsConfig(list, 'fullSync');
      if (list.length > 0) {
        fullSyncPaths.value = list;
      }
    }

    // 3. 增量同步 (increment_sync_strm_paths)
    if (customIncrementSyncPaths.value) {
      config.increment_sync_strm_paths = generatePathsConfig(incrementSyncPaths.value, 'incrementSync');
    } else {
      const list = unifiedPaths.value
        .filter(p => p.enable_inc && (p.local?.trim() || p.remote?.trim()))
        .map(p => ({
          local: p.local?.trim() || '',
          remote: p.remote?.trim() || '',
        }));
      config.increment_sync_strm_paths = generatePathsConfig(list, 'incrementSync');
      if (list.length > 0) {
        incrementSyncPaths.value = list;
      }
    }

    // 4. 监控115生活事件 (monitor_life_paths)
    if (customMonitorLifePaths.value) {
      config.monitor_life_paths = generatePathsConfig(monitorLifePaths.value, 'monitorLife');
    } else {
      const list = unifiedPaths.value
        .filter(p => p.enable_life && (p.local?.trim() || p.remote?.trim()))
        .map(p => ({
          local: p.local?.trim() || '',
          remote: p.remote?.trim() || '',
        }));
      config.monitor_life_paths = generatePathsConfig(list, 'monitorLife');
      if (list.length > 0) {
        monitorLifePaths.value = list;
      }
    }

    // 5. API STRM 生成路径 (api_strm_config 与 api_strm_mp_mediaserver_paths)
    const validUnifiedMp = unifiedMpPaths.value.filter(p => p.local?.trim() || p.remote?.trim());
    if (customApiStrmPaths.value) {
      config.api_strm_config = (apiStrmPaths.value || [])
        .filter(p => p.local?.trim() && p.remote?.trim())
        .map(p => ({ local_path: p.local.trim(), pan_path: p.remote.trim() }));
      config.api_strm_mp_mediaserver_paths = generatePathsConfig(apiStrmMPPaths.value, 'apiStrm-mp');
    } else {
      const list = unifiedPaths.value
        .filter(p => p.local?.trim() && p.remote?.trim())
        .map(p => ({
          local_path: p.local.trim(),
          pan_path: p.remote.trim(),
        }));
      config.api_strm_config = list;
      config.api_strm_mp_mediaserver_paths = generatePathsConfig(validUnifiedMp, 'apiStrm-mp');
      if (list.length > 0) {
        apiStrmPaths.value = list.map(p => ({ local: p.local_path, remote: p.pan_path }));
      }
      if (validUnifiedMp.length > 0) {
        apiStrmMPPaths.value = JSON.parse(JSON.stringify(validUnifiedMp));
      }
    }

    // 6. MP-MediaServer 转换路径 (未开启自定义时分发至各子项)
    if (!customTransferPaths.value) {
      config.transfer_mp_mediaserver_paths = generatePathsConfig(validUnifiedMp, 'mp');
      transferMpPaths.value = validUnifiedMp.length > 0 ? JSON.parse(JSON.stringify(validUnifiedMp)) : [{ local: '', remote: '' }];
    }
    if (!customIncrementSyncPaths.value) {
      config.increment_sync_mp_mediaserver_paths = generatePathsConfig(validUnifiedMp, 'increment-mp');
      incrementSyncMPPaths.value = validUnifiedMp.length > 0 ? JSON.parse(JSON.stringify(validUnifiedMp)) : [{ local: '', remote: '' }];
    }
    if (!customMonitorLifePaths.value) {
      config.monitor_life_mp_mediaserver_paths = generatePathsConfig(validUnifiedMp, 'monitorLifeMp');
      monitorLifeMpPaths.value = validUnifiedMp.length > 0 ? JSON.parse(JSON.stringify(validUnifiedMp)) : [{ local: '', remote: '' }];
    }
  };

  // ============================================================
  // config 字符串 → 路径数组 (immediate watchers)
  // ============================================================

  watch(() => config.transfer_monitor_paths, (newVal) => {
    if (!newVal) {
      transferPaths.value = [{ local: '', remote: '', cd2Prefix: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      transferPaths.value = paths.map(path => {
        const parts = path.split('#');
        const local = parts[0] || '';
        const fullRemote = parts[1] || '';
        const prefix = parts[2]?.trim() || '';
        let remote = fullRemote;
        if (prefix) {
          const normPrefix = prefix.replace(/^\/+/, '').replace(/\/+$/, '');
          const normFull = fullRemote.replace(/^\/+/, '').replace(/\/+$/, '');
          if (normFull === normPrefix || normFull.startsWith(normPrefix + '/')) {
            const rest = normFull.slice(normPrefix.length);
            remote = (rest.startsWith('/') ? rest : '/' + rest) || '';
          }
        }
        return { local, remote, cd2Prefix: prefix };
      });
      if (transferPaths.value.length === 0) {
        transferPaths.value = [{ local: '', remote: '', cd2Prefix: '' }];
      }
    } catch (e) {
      console.error('解析transfer_monitor_paths出错:', e);
      transferPaths.value = [{ local: '', remote: '', cd2Prefix: '' }];
    }
  }, { immediate: true });

  watch(() => config.transfer_mp_mediaserver_paths, (newVal) => {
    if (!newVal) {
      transferMpPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      transferMpPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (transferMpPaths.value.length === 0) {
        transferMpPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析transfer_mp_mediaserver_paths出错:', e);
      transferMpPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.full_sync_strm_paths, (newVal) => {
    if (!newVal) {
      fullSyncPaths.value = [{ local: '', remote: '', enabled: true }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      fullSyncPaths.value = paths.map(path => {
        const parts = path.split('#');
        // 无第三段（旧格式）或第三段非 '0' 时均为开启；仅第三段为 '0' 时为关闭
        const enabled = parts.length < 3 || parts[2].trim() !== '0';
        return { local: parts[0] || '', remote: parts[1] || '', enabled };
      });
      if (fullSyncPaths.value.length === 0) {
        fullSyncPaths.value = [{ local: '', remote: '', enabled: true }];
      }
    } catch (e) {
      console.error('解析full_sync_strm_paths出错:', e);
      fullSyncPaths.value = [{ local: '', remote: '', enabled: true }];
    }
  }, { immediate: true });

  watch(() => config.increment_sync_strm_paths, (newVal) => {
    if (!newVal) {
      incrementSyncPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      incrementSyncPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (incrementSyncPaths.value.length === 0) {
        incrementSyncPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析increment_sync_strm_paths出错:', e);
      incrementSyncPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.increment_sync_mp_mediaserver_paths, (newVal) => {
    if (!newVal) {
      incrementSyncMPPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      incrementSyncMPPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (incrementSyncMPPaths.value.length === 0) {
        incrementSyncMPPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析increment_sync_mp_mediaserver_paths出错:', e);
      incrementSyncMPPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.monitor_life_paths, (newVal) => {
    if (!newVal) {
      monitorLifePaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      monitorLifePaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (monitorLifePaths.value.length === 0) {
        monitorLifePaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析monitor_life_paths出错:', e);
      monitorLifePaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.monitor_life_mp_mediaserver_paths, (newVal) => {
    if (!newVal) {
      monitorLifeMpPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      monitorLifeMpPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (monitorLifeMpPaths.value.length === 0) {
        monitorLifeMpPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析monitor_life_mp_mediaserver_paths出错:', e);
      monitorLifeMpPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.pan_transfer_paths, (newVal) => {
    if (!newVal) {
      panTransferPaths.value = [{ path: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      panTransferPaths.value = paths.map(path => {
        return { path };
      });
      if (panTransferPaths.value.length === 0) {
        panTransferPaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析pan_transfer_paths出错:', e);
      panTransferPaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(() => config.api_strm_config, (newVal) => {
    if (!newVal || !Array.isArray(newVal)) {
      apiStrmPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      apiStrmPaths.value = newVal.map(item => ({
        local: item.local_path || '',
        remote: item.pan_path || ''
      }));
      if (apiStrmPaths.value.length === 0) {
        apiStrmPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析api_strm_config出错:', e);
      apiStrmPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.sync_del_p115_library_path, (newVal) => {
    if (!newVal) {
      syncDelLibraryPaths.value = [{ mediaserver: '', moviepilot: '', p115: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      syncDelLibraryPaths.value = paths.map(path => {
        const parts = path.split('#');
        return {
          mediaserver: parts[0] || '',
          moviepilot: parts[1] || '',
          p115: parts[2] || ''
        };
      });
      if (syncDelLibraryPaths.value.length === 0) {
        syncDelLibraryPaths.value = [{ mediaserver: '', moviepilot: '', p115: '' }];
      }
    } catch (e) {
      console.error('解析sync_del_p115_library_path出错:', e);
      syncDelLibraryPaths.value = [{ mediaserver: '', moviepilot: '', p115: '' }];
    }
  }, { immediate: true });

  watch(() => config.api_strm_mp_mediaserver_paths, (newVal) => {
    if (!newVal) {
      apiStrmMPPaths.value = [{ local: '', remote: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      apiStrmMPPaths.value = paths.map(path => {
        const parts = path.split('#');
        return { local: parts[0] || '', remote: parts[1] || '' };
      });
      if (apiStrmMPPaths.value.length === 0) {
        apiStrmMPPaths.value = [{ local: '', remote: '' }];
      }
    } catch (e) {
      console.error('解析api_strm_mp_mediaserver_paths出错:', e);
      apiStrmMPPaths.value = [{ local: '', remote: '' }];
    }
  }, { immediate: true });

  watch(() => config.share_recieve_paths, (newVal) => {
    if (!newVal || !Array.isArray(newVal)) {
      shareReceivePaths.value = [{ path: '' }];
      return;
    }
    try {
      shareReceivePaths.value = newVal.map(path => {
        return { path: typeof path === 'string' ? path : '' };
      });
      if (shareReceivePaths.value.length === 0) {
        shareReceivePaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析share_recieve_paths出错:', e);
      shareReceivePaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(() => config.offline_download_paths, (newVal) => {
    if (!newVal || !Array.isArray(newVal)) {
      offlineDownloadPaths.value = [{ path: '' }];
      return;
    }
    try {
      offlineDownloadPaths.value = newVal.map(path => {
        return { path: typeof path === 'string' ? path : '' };
      });
      if (offlineDownloadPaths.value.length === 0) {
        offlineDownloadPaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析offline_download_paths出错:', e);
      offlineDownloadPaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(() => config.transfer_monitor_scrape_metadata_exclude_paths, (newVal) => {
    if (typeof newVal !== 'string' || !newVal.trim()) {
      transferExcludePaths.value = [{ path: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      transferExcludePaths.value = paths.map(p => ({ path: p }));
      if (transferExcludePaths.value.length === 0) {
        transferExcludePaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析 transfer_monitor_scrape_metadata_exclude_paths 出错:', e);
      transferExcludePaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(transferExcludePaths, (newVal) => {
    if (!Array.isArray(newVal)) return;
    const pathsString = newVal
      .map(item => item.path?.trim())
      .filter(p => p)
      .join('\n');
    if (config.transfer_monitor_scrape_metadata_exclude_paths !== pathsString) {
      config.transfer_monitor_scrape_metadata_exclude_paths = pathsString;
    }
  }, { deep: true });

  watch(() => config.increment_sync_scrape_metadata_exclude_paths, (newVal) => {
    if (typeof newVal !== 'string' || !newVal.trim()) {
      incrementSyncExcludePaths.value = [{ path: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      incrementSyncExcludePaths.value = paths.map(p => ({ path: p }));
      if (incrementSyncExcludePaths.value.length === 0) {
        incrementSyncExcludePaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析 increment_sync_scrape_metadata_exclude_paths 出错:', e);
      incrementSyncExcludePaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(incrementSyncExcludePaths, (newVal) => {
    if (!Array.isArray(newVal)) return;
    const pathsString = newVal
      .map(item => item.path?.trim())
      .filter(p => p)
      .join('\n');
    if (config.increment_sync_scrape_metadata_exclude_paths !== pathsString) {
      config.increment_sync_scrape_metadata_exclude_paths = pathsString;
    }
  }, { deep: true });

  watch(() => config.monitor_life_scrape_metadata_exclude_paths, (newVal) => {
    if (typeof newVal !== 'string' || !newVal.trim()) {
      monitorLifeExcludePaths.value = [{ path: '' }];
      return;
    }
    try {
      const paths = newVal.split('\n').filter(line => line.trim());
      monitorLifeExcludePaths.value = paths.map(p => ({ path: p }));
      if (monitorLifeExcludePaths.value.length === 0) {
        monitorLifeExcludePaths.value = [{ path: '' }];
      }
    } catch (e) {
      console.error('解析 monitor_life_scrape_metadata_exclude_paths 出错:', e);
      monitorLifeExcludePaths.value = [{ path: '' }];
    }
  }, { immediate: true });

  watch(monitorLifeExcludePaths, (newVal) => {
    if (!Array.isArray(newVal)) return;
    const pathsString = newVal
      .map(item => item.path?.trim())
      .filter(p => p)
      .join('\n');
    if (config.monitor_life_scrape_metadata_exclude_paths !== pathsString) {
      config.monitor_life_scrape_metadata_exclude_paths = pathsString;
    }
  }, { deep: true });

  // 监听 full_sync_remove_unless_strm 变化，当禁用时自动禁用依赖的配置项
  watch(() => config.full_sync_remove_unless_strm, (newVal) => {
    if (!newVal) {
      config.full_sync_remove_unless_dir = false;
      config.full_sync_remove_unless_file = false;
      config.full_sync_cleanup_confirm_mode = "none";
    }
  });

  // 监听 increment_sync_remove_unless_strm 变化，当禁用时自动禁用依赖的配置项
  watch(() => config.increment_sync_remove_unless_strm, (newVal) => {
    if (!newVal) {
      config.increment_sync_remove_unless_dir = false;
      config.increment_sync_remove_unless_file = false;
    }
  });

  // ============================================================
  // 路径增删函数
  // ============================================================

  const addPath = (type) => {
    switch (type) {
      case 'unified':
        unifiedPaths.value.push({
          local: '',
          remote: '',
          cd2Prefix: '',
          enable_transfer: true,
          enable_full: true,
          enable_inc: true,
          enable_life: true,
        });
        break;
      case 'unified-mp':
        unifiedMpPaths.value.push({ local: '', remote: '' });
        break;
      case 'transfer': transferPaths.value.push({ local: '', remote: '', cd2Prefix: '' }); break;
      case 'mp': transferMpPaths.value.push({ local: '', remote: '' }); break;
      case 'fullSync': fullSyncPaths.value.push({ local: '', remote: '', enabled: true }); break;
      case 'incrementSync': incrementSyncPaths.value.push({ local: '', remote: '' }); break;
      case 'increment-mp': incrementSyncMPPaths.value.push({ local: '', remote: '' }); break;
      case 'monitorLife': monitorLifePaths.value.push({ local: '', remote: '' }); break;
      case 'monitorLifeMp': monitorLifeMpPaths.value.push({ local: '', remote: '' }); break;
      case 'apiStrm': apiStrmPaths.value.push({ local: '', remote: '' }); break;
      case 'apiStrm-mp': apiStrmMPPaths.value.push({ local: '', remote: '' }); break;
      case 'syncDelLibrary': syncDelLibraryPaths.value.push({ mediaserver: '', moviepilot: '', p115: '' }); break;
      case 'directoryUpload': directoryUploadPaths.value.push({ src: '', dest_remote: '', dest_local: '', dest_strm: '', delete: false }); break;
      case 'fuseStrmTakeover': fuseStrmTakeoverRules.value.push({ extensions: '', names: '', paths: '', _use_extensions: false, _use_names: false, _use_paths: false }); break;
    }
  };

  const removePath = (index, type) => {
    switch (type) {
      case 'unified':
        unifiedPaths.value.splice(index, 1);
        if (unifiedPaths.value.length === 0) {
          unifiedPaths.value = [{
            local: '',
            remote: '',
            cd2Prefix: '',
            enable_transfer: true,
            enable_full: true,
            enable_inc: true,
            enable_life: true,
          }];
        }
        break;
      case 'unified-mp':
        unifiedMpPaths.value.splice(index, 1);
        if (unifiedMpPaths.value.length === 0) {
          unifiedMpPaths.value = [{ local: '', remote: '' }];
        }
        break;
      case 'transfer':
        transferPaths.value.splice(index, 1);
        if (transferPaths.value.length === 0) transferPaths.value = [{ local: '', remote: '', cd2Prefix: '' }];
        break;
      case 'mp':
        transferMpPaths.value.splice(index, 1);
        if (transferMpPaths.value.length === 0) transferMpPaths.value = [{ local: '', remote: '' }];
        break;
      case 'fullSync':
        fullSyncPaths.value.splice(index, 1);
        if (fullSyncPaths.value.length === 0) fullSyncPaths.value = [{ local: '', remote: '', enabled: true }];
        break;
      case 'incrementSync':
        incrementSyncPaths.value.splice(index, 1);
        if (incrementSyncPaths.value.length === 0) incrementSyncPaths.value = [{ local: '', remote: '' }];
        break;
      case 'increment-mp':
        incrementSyncMPPaths.value.splice(index, 1);
        if (incrementSyncMPPaths.value.length === 0) incrementSyncMPPaths.value = [{ local: '', remote: '' }];
        break;
      case 'monitorLife':
        monitorLifePaths.value.splice(index, 1);
        if (monitorLifePaths.value.length === 0) monitorLifePaths.value = [{ local: '', remote: '' }];
        break;
      case 'monitorLifeMp':
        monitorLifeMpPaths.value.splice(index, 1);
        if (monitorLifeMpPaths.value.length === 0) monitorLifeMpPaths.value = [{ local: '', remote: '' }];
        break;
      case 'apiStrm':
        apiStrmPaths.value.splice(index, 1);
        if (apiStrmPaths.value.length === 0) apiStrmPaths.value = [{ local: '', remote: '' }];
        break;
      case 'apiStrm-mp':
        apiStrmMPPaths.value.splice(index, 1);
        if (apiStrmMPPaths.value.length === 0) apiStrmMPPaths.value = [{ local: '', remote: '' }];
        break;
      case 'syncDelLibrary':
        syncDelLibraryPaths.value.splice(index, 1);
        if (syncDelLibraryPaths.value.length === 0) syncDelLibraryPaths.value = [{ mediaserver: '', moviepilot: '', p115: '' }];
        break;
      case 'directoryUpload':
        directoryUploadPaths.value.splice(index, 1);
        if (directoryUploadPaths.value.length === 0) directoryUploadPaths.value = [{ src: '', dest_remote: '', dest_local: '', dest_strm: '', delete: false }];
        break;
      case 'fuseStrmTakeover':
        fuseStrmTakeoverRules.value.splice(index, 1);
        if (fuseStrmTakeoverRules.value.length === 0) fuseStrmTakeoverRules.value = [{ extensions: '', names: '', paths: '', _use_extensions: false, _use_names: false, _use_paths: false }];
        break;
    }
  };

  const addPanTransferPath = () => { panTransferPaths.value.push({ path: '' }); };
  const removePanTransferPath = (index) => {
    panTransferPaths.value.splice(index, 1);
    if (panTransferPaths.value.length === 0) panTransferPaths.value = [{ path: '' }];
  };

  const addShareReceivePath = () => { shareReceivePaths.value.push({ path: '' }); };
  const removeShareReceivePath = (index) => {
    shareReceivePaths.value.splice(index, 1);
    if (shareReceivePaths.value.length === 0) shareReceivePaths.value = [{ path: '' }];
  };

  const addOfflineDownloadPath = () => { offlineDownloadPaths.value.push({ path: '' }); };
  const removeOfflineDownloadPath = (index) => {
    offlineDownloadPaths.value.splice(index, 1);
    if (offlineDownloadPaths.value.length === 0) offlineDownloadPaths.value = [{ path: '' }];
  };

  return {
    // 统一媒体库路径映射 (方案 A)
    unifiedPaths,
    unifiedMpPaths,
    customTransferPaths,
    customFullSyncPaths,
    customIncrementSyncPaths,
    customMonitorLifePaths,
    customApiStrmPaths,
    reconcileUnifiedPaths,
    syncAllPathsToConfig,
    // Path refs
    transferPaths,
    transferMpPaths,
    fullSyncPaths,
    incrementSyncPaths,
    incrementSyncMPPaths,
    monitorLifePaths,
    monitorLifeMpPaths,
    apiStrmPaths,
    apiStrmMPPaths,
    panTransferPaths,
    shareReceivePaths,
    offlineDownloadPaths,
    transferExcludePaths,
    incrementSyncExcludePaths,
    monitorLifeExcludePaths,
    directoryUploadPaths,
    syncDelLibraryPaths,
    fuseStrmTakeoverRules,
    // Utility functions
    normalizePath,
    normalizePathJoin,
    generatePathsConfig,
    getPathKey,
    getMpKey,
    // Add/remove functions
    addPath,
    removePath,
    addPanTransferPath,
    removePanTransferPath,
    addShareReceivePath,
    removeShareReceivePath,
    addOfflineDownloadPath,
    removeOfflineDownloadPath,
  };
}
