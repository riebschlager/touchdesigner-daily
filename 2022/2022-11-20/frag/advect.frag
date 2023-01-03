uniform float uDelta;
uniform float uDiffusion;

out vec4 fragColor;

void main()
{
	vec2 size = uTD2DInfos[1].res.xy;
	vec2 coord = vUV.xy - uDelta * texture(sTD2DInputs[1], vUV.xy).xy * size;
	vec4 result = texture(sTD2DInputs[0], coord);
	float decay = 1.0 + uDiffusion * uDelta;
	vec4 color = result / decay;
	fragColor = TDOutputSwizzle(color);
}
