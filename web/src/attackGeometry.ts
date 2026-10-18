// Same four-corner perspective transform as the executor's Projection.
export function mapTransform(corners: number[][]) {
  if (corners.length !== 4) return null;
  const [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]=corners;
  const dx1=x1-x2,dx2=x3-x2,dx3=x0-x1+x2-x3;
  const dy1=y1-y2,dy2=y3-y2,dy3=y0-y1+y2-y3;
  const det=dx1*dy2-dx2*dy1;
  if(Math.abs(det)<1e-6)return null;
  const g=(dx3*dy2-dx2*dy3)/det,h=(dx1*dy3-dx3*dy1)/det;
  return [x1-x0+g*x1,x3-x0+h*x3,x0,y1-y0+g*y1,y3-y0+h*y3,y0,g,h,1];
}
export function inverse(m:number[]){
  const [a,b,c,d,e,f,g,h,i]=m;
  const out=[e*i-f*h,c*h-b*i,b*f-c*e,f*g-d*i,a*i-c*g,c*d-a*f,d*h-e*g,b*g-a*h,a*e-b*d];
  const det=a*out[0]+b*out[3]+c*out[6];
  return Math.abs(det)<1e-8?null:out.map(n=>n/det);
}
export function transform(m:number[],x:number,y:number){
  const z=m[6]*x+m[7]*y+m[8];
  return [(m[0]*x+m[1]*y+m[2])/z,(m[3]*x+m[4]*y+m[5])/z];
}
