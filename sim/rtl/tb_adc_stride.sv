`timescale 1ns/1ps
module tb_adc_stride;
 reg clk=0,bus_clk=0,reset_n=0,request=0;
 always #10 clk=~clk;
 always #7 bus_clk=~bus_clk;
 reg [15:0] data=0,stride=1;
 always @(negedge clk) data<=data+1'b1;
 reg [9:0] address=0;
 wire done;wire [16:0] word;
 adc_capture dut(clk,reset_n,request,data,1'b0,done,bus_clk,address,word,stride,11'd1024);
 integer i,j; reg [15:0] prior; integer steps[0:3];
 initial begin
  steps[0]=1;steps[1]=5;steps[2]=16;steps[3]=256;
  #51;reset_n=1;
  for(j=0;j<4;j=j+1) begin
   @(negedge bus_clk);stride=steps[j];
   repeat(4) @(negedge bus_clk);
   request=~request;wait(done==request);
   for(i=0;i<1024;i=i+1) begin
    @(negedge bus_clk);address=i;
    repeat(2) @(negedge bus_clk);
    if(i>0 && ((word[15:0]-prior)&16'hffff)!=steps[j]) $fatal(1,"stride mismatch %d %d",j,i);
    prior=word[15:0];
   end
  end
  $display("PASS ADC capture strides 1/5/16/256, contiguous hardware timebase");$finish;
 end
 initial begin #10000000;$fatal(1,"timeout");end
endmodule
