/**
 * Size and ground Mixamo humanoids. Box3.setFromObject cannot be used on a fresh skeleton
 * clone: its bone matrices are still zero until the first render, so the skin collapses to
 * a point and the measured height is ~0.
 */

function skinnedBounds(THREE, root, out) {
  root.updateMatrixWorld(true);
  out.makeEmpty();
  const b = new THREE.Box3();
  root.traverse((o) => {
    if (!o.isMesh) return;
    if (o.isSkinnedMesh) {
      o.skeleton.update();
      o.computeBoundingBox();
      o.computeBoundingSphere();
      b.copy(o.boundingBox);
    } else {
      if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
      b.copy(o.geometry.boundingBox);
    }
    out.union(b.applyMatrix4(o.matrixWorld));
  });
  return out;
}

/**
 * Scale `root` (unparented, rest pose) to `targetH` metres tall with its feet at y = 0.
 * Returns the hips height above the feet, or null when the rig has no Hips bone.
 */
export function fitHumanoid(THREE, root, targetH) {
  const box = skinnedBounds(THREE, root, new THREE.Box3());
  const h = box.max.y - box.min.y;
  if (h > 1e-6) root.scale.multiplyScalar(targetH / h);
  skinnedBounds(THREE, root, box);
  root.position.y -= box.min.y;
  root.updateMatrixWorld(true);

  let hips = null;
  root.traverse((o) => {
    if (!hips && o.isBone && /hips$/i.test(o.name)) hips = o;
  });
  if (!hips) return null;
  return hips.getWorldPosition(new THREE.Vector3()).y;
}
