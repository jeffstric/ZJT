// 相机 3D 预览模块
// 使用 Canvas 2D 绘制简化的 3D 立方体和相机视角

function initCameraPreview(canvasEl, camera) {
  if (!canvasEl) return;
  updateCameraPreview(canvasEl, camera);
}

function updateCameraPreview(canvasEl, camera) {
  if (!canvasEl) return;
  
  const ctx = canvasEl.getContext('2d');
  const width = canvasEl.width;
  const height = canvasEl.height;
  
  const yaw = camera.yaw ?? 0;
  const dolly = camera.dolly ?? 0;
  const pitch = camera.pitch ?? 0;
  
  ctx.clearRect(0, 0, width, height);
  
  const centerX = width / 2;
  const centerY = height / 2;
  const cubeSize = 60;
  
  ctx.save();
  ctx.translate(centerX, centerY);
  
  drawCube(ctx, cubeSize);
  drawCamera(ctx, yaw, dolly, pitch, cubeSize);
  drawLabels(ctx, yaw, pitch, width, height);
  
  ctx.restore();
}

function drawCube(ctx, size) {
  const s = size / 2;
  
  const vertices = [
    [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
    [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s]
  ];
  
  const rotY = Math.PI / 6;
  const rotX = Math.PI / 8;
  
  const projected = vertices.map(v => {
    let [x, y, z] = v;
    
    let tempZ = z * Math.cos(rotY) - x * Math.sin(rotY);
    let tempX = z * Math.sin(rotY) + x * Math.cos(rotY);
    z = tempZ;
    x = tempX;
    
    let tempY = y * Math.cos(rotX) - z * Math.sin(rotX);
    tempZ = y * Math.sin(rotX) + z * Math.cos(rotX);
    y = tempY;
    z = tempZ;
    
    return [x, y];
  });
  
  const edges = [
    [0, 1], [1, 2], [2, 3], [3, 0],
    [4, 5], [5, 6], [6, 7], [7, 4],
    [0, 4], [1, 5], [2, 6], [3, 7]
  ];
  
  ctx.strokeStyle = 'rgba(34, 197, 94, 0.6)';
  ctx.lineWidth = 2;
  
  edges.forEach(([i, j]) => {
    ctx.beginPath();
    ctx.moveTo(projected[i][0], projected[i][1]);
    ctx.lineTo(projected[j][0], projected[j][1]);
    ctx.stroke();
  });
  
  ctx.fillStyle = 'rgba(34, 197, 94, 0.1)';
  ctx.beginPath();
  ctx.moveTo(projected[0][0], projected[0][1]);
  ctx.lineTo(projected[1][0], projected[1][1]);
  ctx.lineTo(projected[2][0], projected[2][1]);
  ctx.lineTo(projected[3][0], projected[3][1]);
  ctx.closePath();
  ctx.fill();
}

function drawCamera(ctx, yaw, dolly, pitch, cubeSize) {
  const yawRad = (yaw * Math.PI) / 180;
  const pitchRad = (pitch * Math.PI) / 180;
  
  const distance = cubeSize * 1.5 - (dolly / 10) * cubeSize * 0.8;
  
  // 相机位置计算：
  // Yaw=0° 时相机在 Z轴负方向（从前方看向立方体）
  // Yaw 负值：相机向左移动
  // Yaw 正值：相机向右移动
  // Pitch 负值：相机向下（仰视 - Low Angle）
  // Pitch 正值：相机向上（俯视 - High Angle）
  const camX = distance * Math.sin(yawRad) * Math.cos(pitchRad);
  const camY = -distance * Math.sin(pitchRad);
  const camZ = -distance * Math.cos(yawRad) * Math.cos(pitchRad);
  
  const rotY = Math.PI / 6;
  const rotX = Math.PI / 8;
  
  let x = camX;
  let y = camY;
  let z = camZ;
  
  let tempZ = z * Math.cos(rotY) - x * Math.sin(rotY);
  let tempX = z * Math.sin(rotY) + x * Math.cos(rotY);
  z = tempZ;
  x = tempX;
  
  let tempY = y * Math.cos(rotX) - z * Math.sin(rotX);
  tempZ = y * Math.sin(rotX) + z * Math.cos(rotX);
  y = tempY;
  
  ctx.fillStyle = '#ef4444';
  ctx.beginPath();
  ctx.arc(x, y, 5, 0, Math.PI * 2);
  ctx.fill();
  
  ctx.strokeStyle = '#ef4444';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x, y);
  
  const dirLength = 20;
  const dirX = -dirLength * Math.sin(yawRad) * Math.cos(pitchRad);
  const dirY = dirLength * Math.sin(pitchRad);
  const dirZ = dirLength * Math.cos(yawRad) * Math.cos(pitchRad);
  
  let dx = dirX;
  let dy = dirY;
  let dz = dirZ;
  
  tempZ = dz * Math.cos(rotY) - dx * Math.sin(rotY);
  tempX = dz * Math.sin(rotY) + dx * Math.cos(rotY);
  dz = tempZ;
  dx = tempX;
  
  tempY = dy * Math.cos(rotX) - dz * Math.sin(rotX);
  dy = tempY;
  
  ctx.lineTo(x + dx, y + dy);
  ctx.stroke();
  
  ctx.beginPath();
  ctx.arc(x + dx, y + dy, 3, 0, Math.PI * 2);
  ctx.fill();
}

function drawLabels(ctx, yaw, pitch, width, height) {
  ctx.fillStyle = '#374151';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  
  const labelX = -width / 2 + 8;
  const labelY = -height / 2 + 8;
  
  ctx.fillText(`左右: ${yaw.toFixed(0)}°`, labelX, labelY);
  ctx.fillText(`俯仰: ${pitch.toFixed(0)}°`, labelX, labelY + 14);
}

if (typeof window !== 'undefined') {
  window.initCameraPreview = initCameraPreview;
  window.updateCameraPreview = updateCameraPreview;
}
