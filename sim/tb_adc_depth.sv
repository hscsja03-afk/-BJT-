`timescale 1ns/1ps
module tb_adc_depth;
 reg clk=0,bus_clk=0,reset_n=0,request=0;
 always #10 clk=~clk;
 always #7 bus_clk=~bus_clk;
 reg [15:0] data=0,stride=1;
 always @(negedge clk) data<=data+1'b1;
 reg [11:0] address=0;
 reg [12:0] count=1024;
 wire done;wire [16:0] word;
 adc_capture #(.ADDR_BITS(12)) dut(clk,reset_n,request,data,1'b0,done,bus_clk,address,word,stride,count);
 integer i,j,k;reg [15:0] prior;integer length,step;
 initial begin
  #51;reset_n=1;
  for(j=0;j<3;j=j+1) begin
   length=j==0?256:(j==1?1024:4096);
   for(k=0;k<3;k=k+1) begin
    step=k==0?1:(k==1?20:256);
    @(negedge bus_clk);stride=step;count=length;
    repeat(4) @(negedge bus_clk);
    request=~request;wait(done==request);
    for(i=0;i<length;i=i+1) begin
     @(negedge bus_clk);address=i;
     repeat(2) @(negedge bus_clk);
     if(i>0 && ((word[15:0]-prior)&16'hffff)!=step) $fatal(1,"depth/stride mismatch %d %d %d",length,step,i);
     prior=word[15:0];
    end
   end
  end
  $display("PASS ADC depths 256/1024/4096 and strides 1/20/256");$finish;
 end
 initial begin #50000000;$fatal(1,"timeout");end
endmodule
