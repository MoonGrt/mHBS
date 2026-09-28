module root_compare_check;
localparam W=256;
reg [391:0] value[0:3];reg [255:0] job_public_root;
reg [5:0] node_bytes;
wire actual = value[2][127:0]==job_public_root[127:0]
                                    && (node_bytes==16 || value[2][191:128]==job_public_root[191:128])
                                    && (node_bytes!=32 || value[2][255:192]==job_public_root[255:192]);
integer checks=0,n,b,i,j;
reg expected;
task check;
begin
 #1; expected=1;
 for(integer k=0;k<node_bytes;k=k+1)
  if(value[2][8*k +:8]!=job_public_root[8*k +:8])expected=0;
 if(actual!==expected)$fatal(1,"root compare n=%0d",node_bytes);
 checks=checks+1;
end
endtask
initial begin
 value[2]=0;
 for(n=16;n<=32;n=n+8)begin
  node_bytes=n;
  for(j=0;j<8;j=j+1)value[2][32*j +:32]=$random;
  job_public_root=value[2][255:0];check();
  for(b=0;b<256;b=b+1)begin
   job_public_root=value[2][255:0];job_public_root[b]=~job_public_root[b];check();
  end
  for(i=0;i<128;i=i+1)begin
   for(j=0;j<8;j=j+1)begin value[2][32*j +:32]=$random;job_public_root[32*j +:32]=$random;end
   if(i%2==0)for(j=0;j<n;j=j+1)job_public_root[8*j +:8]=value[2][8*j +:8];
   check();
  end
 end
 $display("ROOT_COMPARE_PASS checks=%0d",checks);$finish;
end
endmodule
