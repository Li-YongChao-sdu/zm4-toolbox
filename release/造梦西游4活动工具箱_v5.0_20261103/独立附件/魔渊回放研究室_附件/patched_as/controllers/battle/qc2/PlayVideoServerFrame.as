package controllers.battle.qc2
{
   import com.game.engine.core.GameFrame;
   import flash.display.Stage;
   import flash.events.Event;
   import modules.ApplicationFacade;
   
   public class PlayVideoServerFrame
   {
       
      
      private var _keys:Array;
      
      private var _deleted:Boolean;
      
      private var k:int = 0;
      
      private var f:int = 1;
      
      private var _testArr:Array;
      
      private var id:int;
      
      private var _lastDate:Date;
      
      private var _elapsedTime:Number = 0;
      
      private var _frameRate:Number = 0;
      
      private var _tempFrameRate:Number = 0;
      
      public function PlayVideoServerFrame(param1:Stage)
      {
         _keys = [];
         super();
         param1.addEventListener("enterFrame",onEnterFrame);
         this.id = Math.random() * 10000;
         SimulateServerFrame.beginReplayObservation(param1);
         param1.addEventListener("enterFrame",onReplayObserve,false,-10000);
      }
      
      private function onReplayObserve(e:Event) : void
      {
         SimulateServerFrame.observeReplayState(this.f);
      }

      public function get frameRate() : Number
      {
         return _frameRate;
      }
      
      public function advanceTime(param1:Number) : void
      {
         onEnterFrame(null);
      }
      
      public function addSendKey(param1:Object) : void
      {
         _keys.push(param1);
      }
      
      private function onEnterFrame(param1:Event) : void
      {
         var _loc3_:Number = NaN;
         var _loc5_:int = 0;
         if(_deleted || GameFrame.current.isPaused)
         {
            _lastDate = null;
            return;
         }
         _loc3_ = 0.03333333333333333;
         var _loc2_:Date = new Date();
         if(!_lastDate)
         {
            _lastDate = _loc2_;
         }
         var _loc4_:Number = _loc2_.time - _lastDate.time;
         _lastDate = _loc2_;
         _elapsedTime += _loc4_;
         if(_elapsedTime < 33)
         {
            return;
         }
         _elapsedTime -= 33;
         if(_testArr)
         {
            k++;
            if(k > _testArr[0])
            {
               _testArr.shift();
               ApplicationFacade.getInstance().sendNotification("OnReceive",_keys);
               _keys.length = 0;
               k = 0;
               if(_testArr.length == 0)
               {
                  _testArr = null;
               }
            }
         }
         else
         {
            k++;
            if(k >= 2 - _frameRate)
            {
            }
            _loc5_ = this._frameRate + 1;
            while(_loc5_ > 0)
            {
               _loc5_--;
               send2();
            }
            _keys.length = 0;
            k = 0;
         }
      }
      
      private function send2() : void
      {
         var _loc2_:Object = PlayPvpVideoCmd.data.frames[0];
         if(!_loc2_)
         {
            return;
         }
         var _loc1_:Object = {};
         _loc1_.frames = [];
         if(_loc2_ && _loc2_.currFrame + 1 == f)
         {
            _loc1_.frames.push(_loc2_);
            PlayPvpVideoCmd.data.frames.shift();
         }
         _loc1_.serFrameNum = f;
         ApplicationFacade.getInstance().sendNotification("qcOnReceive2",{"message":_loc1_});
         f++;
      }
      
      public function destroy() : void
      {
         SimulateServerFrame.finishReplayObservation("video_destroyed");
         GameFrame.stage.removeEventListener("enterFrame",onReplayObserve);
         _deleted = true;
         GameFrame.stage.removeEventListener("enterFrame",onEnterFrame);
      }
      
      public function Slow() : void
      {
      }
      
      public function Start() : void
      {
         GameFrame.stage.addEventListener("enterFrame",onEnterFrame);
      }
      
      public function SetFrameRate(param1:Number) : void
      {
         _frameRate = param1;
      }
   }
}
