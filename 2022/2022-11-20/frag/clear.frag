uniform float uClear;

out vec4 fragColor;
void main()
{
	vec4 color = uClear * texture(sTD2DInputs[0], vUV.xy);
	fragColor = TDOutputSwizzle(color);
}
