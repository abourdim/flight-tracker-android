/* ============================================================================
 * web-bluetooth-shim.js
 * Translates the W3C Web Bluetooth API (navigator.bluetooth) into calls to
 * @capacitor-community/bluetooth-le, so that web apps written for Chrome's
 * Web Bluetooth work unmodified inside a Capacitor Android WebView.
 *
 * Version: 1.0.0  | License: MIT  | (c) 2026 workshop-diy.org
 *
 * Coverage:
 *   ✓ navigator.bluetooth.requestDevice({ filters | acceptAllDevices, optionalServices })
 *   ✓ BluetoothDevice.gatt.connect() / disconnect()
 *   ✓ Server.getPrimaryService(uuid) / getPrimaryServices()
 *   ✓ Service.getCharacteristic(uuid) / getCharacteristics()
 *   ✓ Characteristic.readValue() → DataView
 *   ✓ Characteristic.writeValue(BufferSource)
 *   ✓ Characteristic.writeValueWithoutResponse(BufferSource)
 *   ✓ Characteristic.startNotifications() / stopNotifications()
 *   ✓ Characteristic.addEventListener('characteristicvaluechanged', cb)
 *   ✓ device.addEventListener('gattserverdisconnected', cb)
 *
 * Limitations:
 *   ✗ getDevices() (paired devices)
 *   ✗ Descriptors API (BluetoothRemoteGATTDescriptor)
 *   ✗ Advertisement watching (watchAdvertisements)
 *   ✗ Server.connected reflects last-known state, not real-time
 * ========================================================================== */
(function () {
  'use strict';

  // Bail out if real Web Bluetooth is already present (running in Chrome desktop)
  if (typeof navigator.bluetooth !== 'undefined') {
    console.log('[ble-shim] navigator.bluetooth already exists, shim not installed');
    return;
  }

  // The Capacitor plugin must be available
  function getBle() {
    if (window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.BluetoothLe) {
      return window.Capacitor.Plugins.BluetoothLe;
    }
    return null;
  }

  if (!getBle()) {
    console.warn('[ble-shim] @capacitor-community/bluetooth-le not loaded yet — will retry on demand');
  }

  // Initialise the plugin once
  let initPromise = null;
  function ensureInit() {
    if (initPromise) return initPromise;
    initPromise = (async () => {
      const ble = getBle();
      if (!ble) throw new Error('Capacitor BluetoothLe plugin not available');
      try {
        await ble.initialize({ androidNeverForLocation: false });
      } catch (e) {
        console.error('[ble-shim] initialize failed:', e);
        throw e;
      }
    })();
    return initPromise;
  }

  // Convert UUID short form (16-bit number) or string into a string
  function uuid(u) {
    if (typeof u === 'number') {
      return u.toString(16).padStart(4, '0').padStart(8, '0') + '-0000-1000-8000-00805f9b34fb';
    }
    return String(u).toLowerCase();
  }

  // Convert hex / base64 / DataView interchange (Capacitor BLE uses DataView)
  function toDataView(bufferSource) {
    if (bufferSource instanceof DataView) return bufferSource;
    if (bufferSource instanceof ArrayBuffer) return new DataView(bufferSource);
    if (ArrayBuffer.isView(bufferSource)) {
      return new DataView(bufferSource.buffer, bufferSource.byteOffset, bufferSource.byteLength);
    }
    throw new TypeError('Expected ArrayBuffer or BufferSource');
  }

  // ---- BluetoothRemoteGATTCharacteristic ----------------------------------
  class GATTCharacteristic extends EventTarget {
    constructor(service, uuidStr) {
      super();
      this.service = service;
      this.uuid = uuidStr;
      this.value = null;
      this.properties = {
        broadcast: false, read: true, writeWithoutResponse: true, write: true,
        notify: true, indicate: false, authenticatedSignedWrites: false,
        reliableWrite: false, writableAuxiliaries: false,
      };
    }

    async readValue() {
      const ble = getBle();
      const dv = await ble.read({
        deviceId: this.service.device.id,
        service: this.service.uuid,
        characteristic: this.uuid,
      });
      this.value = dv;
      this.dispatchEvent(new CustomEvent('characteristicvaluechanged', { detail: dv }));
      return dv;
    }

    async writeValue(data) {
      const ble = getBle();
      await ble.write({
        deviceId: this.service.device.id,
        service: this.service.uuid,
        characteristic: this.uuid,
        value: toDataView(data),
      });
    }

    async writeValueWithResponse(data) { return this.writeValue(data); }

    async writeValueWithoutResponse(data) {
      const ble = getBle();
      await ble.writeWithoutResponse({
        deviceId: this.service.device.id,
        service: this.service.uuid,
        characteristic: this.uuid,
        value: toDataView(data),
      });
    }

    async startNotifications() {
      const ble = getBle();
      await ble.startNotifications(
        this.service.device.id,
        this.service.uuid,
        this.uuid,
        (dv) => {
          this.value = dv;
          this.dispatchEvent(new CustomEvent('characteristicvaluechanged', { detail: dv }));
        }
      );
      return this;
    }

    async stopNotifications() {
      const ble = getBle();
      await ble.stopNotifications({
        deviceId: this.service.device.id,
        service: this.service.uuid,
        characteristic: this.uuid,
      });
      return this;
    }
  }

  // EventTarget addEventListener already gives us value-changed events; alias detail to event.target.value
  // Patch addEventListener to mimic Web Bluetooth's e.target.value access pattern
  const origAddEL = GATTCharacteristic.prototype.addEventListener;
  GATTCharacteristic.prototype.addEventListener = function (type, listener, options) {
    if (type === 'characteristicvaluechanged' && typeof listener === 'function') {
      const wrapped = (e) => {
        // populate event.target.value (already set on this.value)
        listener.call(this, e);
      };
      return origAddEL.call(this, type, wrapped, options);
    }
    return origAddEL.call(this, type, listener, options);
  };

  // ---- BluetoothRemoteGATTService -----------------------------------------
  class GATTService {
    constructor(device, uuidStr) {
      this.device = device;
      this.uuid = uuidStr;
      this.isPrimary = true;
      this._chars = new Map();
    }

    async getCharacteristic(uuidArg) {
      const u = uuid(uuidArg);
      let c = this._chars.get(u);
      if (!c) { c = new GATTCharacteristic(this, u); this._chars.set(u, c); }
      return c;
    }

    async getCharacteristics() {
      // Capacitor's getServices returns services + characteristics
      const ble = getBle();
      const services = await ble.getServices(this.device.id);
      const svc = services.find(s => s.uuid.toLowerCase() === this.uuid);
      if (!svc) return [];
      return svc.characteristics.map(ch => {
        const u = ch.uuid.toLowerCase();
        let c = this._chars.get(u);
        if (!c) { c = new GATTCharacteristic(this, u); this._chars.set(u, c); }
        return c;
      });
    }
  }

  // ---- BluetoothRemoteGATTServer ------------------------------------------
  class GATTServer {
    constructor(device) {
      this.device = device;
      this.connected = false;
      this._services = new Map();
    }

    async connect() {
      const ble = getBle();
      await ensureInit();
      await ble.connect(this.device.id, () => {
        this.connected = false;
        this.device.dispatchEvent(new Event('gattserverdisconnected'));
      });
      this.connected = true;
      return this;
    }

    async disconnect() {
      const ble = getBle();
      try { await ble.disconnect(this.device.id); } catch (e) {}
      this.connected = false;
    }

    async getPrimaryService(uuidArg) {
      const u = uuid(uuidArg);
      let s = this._services.get(u);
      if (!s) { s = new GATTService(this.device, u); this._services.set(u, s); }
      return s;
    }

    async getPrimaryServices() {
      const ble = getBle();
      const list = await ble.getServices(this.device.id);
      return list.map(s => {
        const u = s.uuid.toLowerCase();
        let svc = this._services.get(u);
        if (!svc) { svc = new GATTService(this.device, u); this._services.set(u, svc); }
        return svc;
      });
    }
  }

  // ---- BluetoothDevice ----------------------------------------------------
  class BluetoothDevice extends EventTarget {
    constructor(deviceId, name) {
      super();
      this.id = deviceId;
      this.name = name;
      this.gatt = new GATTServer(this);
    }
  }

  // ---- navigator.bluetooth ------------------------------------------------
  const bluetooth = {
    async getAvailability() { return true; },

    async requestDevice(options = {}) {
      const ble = getBle();
      if (!ble) throw new Error('Capacitor BluetoothLe plugin not available');
      await ensureInit();

      // Build options for Capacitor — services come from filters[].services or acceptAllDevices
      const reqOpts = {};
      const services = new Set();
      if (Array.isArray(options.filters)) {
        for (const f of options.filters) {
          if (Array.isArray(f.services)) {
            for (const s of f.services) services.add(uuid(s));
          }
          if (typeof f.namePrefix === 'string') reqOpts.namePrefix = f.namePrefix;
          if (typeof f.name === 'string') reqOpts.name = f.name;
        }
      }
      if (Array.isArray(options.optionalServices)) {
        for (const s of options.optionalServices) services.add(uuid(s));
      }
      if (services.size > 0) reqOpts.services = Array.from(services);
      if (options.acceptAllDevices) reqOpts.allowDuplicates = false;

      const dev = await ble.requestDevice(reqOpts);
      return new BluetoothDevice(dev.deviceId, dev.name || dev.deviceId);
    },
  };

  Object.defineProperty(navigator, 'bluetooth', {
    value: bluetooth,
    configurable: false,
    writable: false,
  });

  console.log('[ble-shim] installed — navigator.bluetooth now bridged via Capacitor BluetoothLe');
})();
