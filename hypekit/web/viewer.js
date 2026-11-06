// three.js model viewer for hypekit GLBs: orbit, animation, the game's sprite + additive materials.
import * as THREE from 'three';
import { GLTFLoader } from './vendor/three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from './vendor/three/addons/controls/OrbitControls.js';

export class Viewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.01, 1000);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x404050, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(3, 5, 4);
    this.scene.add(sun);
    this.clock = new THREE.Clock();
    this.mixer = null;
    this.action = null;
    this.root = null;
    this.playing = true;
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.renderer.setAnimationLoop(() => this.frame());
  }

  resize() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  clear() {
    if (!this.root) return;
    this.scene.remove(this.root);
    this.root.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) { o.material.map?.dispose(); o.material.dispose(); }
    });
    this.root = this.mixer = this.action = null;
  }

  // game materials: camera-facing unlit sprites (Playmobil faces), additive light textures, plastic sheen
  prepare(root) {
    const q = new THREE.Quaternion();
    root.traverse(o => {
      if (o.userData.sprite) {
        o.traverse(m => {
          if (!m.isMesh) return;
          const old = m.material;
          m.material = new THREE.MeshBasicMaterial({ map: old.map, alphaTest: 0.5, side: THREE.DoubleSide,
            transparent: !!old.userData.additive, blending: old.userData.additive ? THREE.AdditiveBlending : THREE.NormalBlending });
          m.material.userData = old.userData;
          old.dispose();
          m.onBeforeRender = (r, sc, cam) => {
            o.parent.getWorldQuaternion(q).invert().multiply(cam.quaternion);
            o.quaternion.copy(q);
            o.updateMatrixWorld(true);
          };
        });
      }
      if (!o.isMesh || o.material.isMeshBasicMaterial) return;
      const m = o.material;
      if (m.map) m.map.anisotropy = 4;
      if (m.userData.additive) { m.transparent = true; m.depthWrite = false; m.blending = THREE.AdditiveBlending; }
      m.roughness = 0.62;
      m.metalness = 0;
    });
  }

  async load(url, { keepView = false } = {}) {
    const gltf = await new GLTFLoader().loadAsync(url);
    this.clear();
    this.root = gltf.scene;
    this.prepare(this.root);
    this.scene.add(this.root);
    this.mixer = new THREE.AnimationMixer(this.root);
    const clip = gltf.animations[0];
    this.duration = clip ? clip.duration : 0;
    if (clip) {
      this.action = this.mixer.clipAction(clip);
      this.action.play();
      this.action.paused = !this.playing;
    }
    this.mixer.update(0);
    if (!keepView) this.frameView();
    return { duration: this.duration, frames: clip ? clip.tracks[0]?.times.length : 0 };
  }

  frameView() {
    this.root.updateMatrixWorld(true);
    const box = new THREE.Box3();
    this.root.traverse(o => { if (o.isMesh && !o.userData.sprite && !o.parent?.userData.sprite) box.expandByObject(o); });
    if (box.isEmpty()) box.setFromObject(this.root);
    const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
    const r = Math.max(size.x, size.y, size.z, 0.05);
    const d = r / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * 0.8;
    this.camera.near = d / 200; this.camera.far = d * 50; this.camera.updateProjectionMatrix();
    this.camera.position.set(c.x + d * 0.55, c.y + d * 0.25, c.z + d * 0.8);
    this.controls.target.copy(c);
    this.controls.update();
  }

  setPlaying(on) { this.playing = on; if (this.action) this.action.paused = !on; }
  get time() { return this.action ? this.action.time : 0; }

  frame() {
    const dt = this.clock.getDelta();
    if (this.mixer && this.playing) this.mixer.update(dt);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
