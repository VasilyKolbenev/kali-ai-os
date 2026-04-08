import { Canvas } from "@react-three/fiber";
import { BlobMaterial } from "./BlobMaterial";

export function Avatar() {
  return (
    <div className="w-80 h-80">
      <Canvas camera={{ position: [0, 0, 4], fov: 45 }}>
        <ambientLight intensity={0.3} />
        <pointLight position={[5, 5, 5]} intensity={0.8} />
        <BlobMaterial />
      </Canvas>
    </div>
  );
}
