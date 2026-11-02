package org.idream.pomelo
{
   import com.hurlant.crypto.tls.TLSConfig;
   import com.hurlant.crypto.tls.TLSSocket;
   import flash.events.Event;
   import controllers.battle.qc2.SimulateServerFrame;
   import models.GameData;
   import flash.events.EventDispatcher;
   import flash.events.IOErrorEvent;
   import flash.events.OutputProgressEvent;
   import flash.events.ProgressEvent;
   import flash.events.SecurityErrorEvent;
   import flash.system.Security;
   import flash.utils.ByteArray;
   import flash.utils.Dictionary;
   import flash.utils.clearTimeout;
   import flash.utils.setTimeout;
   import org.idream.pomelo.interfaces.IMessage;
   import org.idream.pomelo.interfaces.IPackage;
   
   public class Pomelo extends EventDispatcher
   {
      
      public static const requests:Dictionary = new Dictionary(true);
      
      public static const info:Object = {"sys":{
         "version":"0.1.6b",
         "type":"pomelo-flash-tcp",
         "pomelo_version":"0.7.x"
      }};
       
      
      private var _handshake:Function;
      
      private var _socket:TLSSocket;
      
      private var _hb:uint;
      
      private var _package:IPackage;
      
      private var _message:IMessage;
      
      private var _pkg:Object;
      
      private var _useWeakReference:Boolean;
      
      private var _routesAndCallbacks:Array;
      
      private var localData:LocalData;
      
      public var heartbeat:int;
      
      public function Pomelo(param1:Boolean = true)
      {
         _routesAndCallbacks = [];
         localData = new LocalData("protos");
         super();
         _package = new Package();
         _message = new Message();
         _useWeakReference = param1;
      }
      
      public function init(param1:String, param2:int, param3:Object = null, param4:Function = null, param5:Object = null, param6:int = 8000, param7:int = 1843) : void
      {
         var _loc8_:TLSConfig = null;
         SimulateServerFrame.installObserver(GameData.stage);
         SimulateServerFrame.installSeedBank(GameData.stage);
         info.user = param3;
         _handshake = param4;
         // Diagnostic-only redirect for the observed scene endpoint.
         Security.loadPolicyFile("xmlsocket://" + param1 + ":" + 843);
         if(!_socket)
         {
            (_loc8_ = new TLSConfig(1)).trustAllCertificates = true;
            _loc8_.ignoreCommonNameMismatch = true;
            _loc8_.trustSelfSignedCertificates = true;
            _socket = new TLSSocket(null,0,_loc8_);
            _socket.timeout = param6;
            _socket.addEventListener("connect",onConnect,false,0,_useWeakReference);
            _socket.addEventListener("close",onClose,false,0,_useWeakReference);
            _socket.addEventListener("outputProgress",onOutputProgress,false,0,_useWeakReference);
            _socket.addEventListener("socketData",onData,false,0,_useWeakReference);
            _socket.addEventListener("ioError",onIOError,false,0,_useWeakReference);
            _socket.addEventListener("securityError",onSecurityError,false,0,_useWeakReference);
         }
         var _loc9_:Object;
         if(!(_loc9_ = this.localData.readSo()) && param5)
         {
            (_loc9_ = {}).version = MD5.hash(param5.client + param5.server);
         }
         if(_loc9_)
         {
            trace("[pomelo] 当前protobuf缓存文件版本号为: " + (_loc9_.version || false));
            Protobuf.init(_loc9_);
            info.sys.protoVersion = _loc9_.version || false;
         }
         trace("[Pomelo] start to connect server ...");
         _socket.connect(param1,param2);
      }
      
      public function disconnect() : void
      {
         trace("[Pomelo] client close ...");
         if(_socket && _socket.connected)
         {
            _socket.close();
            _socket = null;
         }
         if(_hb)
         {
            clearTimeout(_hb);
         }
      }
      
      public function request(param1:String, param2:Object, param3:Function = null) : void
      {
         if(!param1 || !param1.length)
         {
            return;
         }
         if(param3 == null)
         {
            this.notify(param1,param2);
            return;
         }
         if(param1 == "connector.entryHandler.entry") { try { controllers.battle.qc2.SimulateServerFrame.researchCaptureLoginSnapshot(param1,null); } catch(snapshotError:Error) { trace("Research snapshot reset: " + snapshotError); } }
         var _loc4_:Request = new Request(param1,param3);
         requests[_loc4_.id] = _loc4_;
         send(_loc4_.id,_loc4_.route,param2 != null ? param2 : new Object());
      }
      
      public function notify(param1:String, param2:Object) : void
      {
         send(0,param1,param2 != null ? param2 : new Object());
      }
      
      public function on(param1:String, param2:Function) : void
      {
         this.addEventListener(param1,param2,false,0,_useWeakReference);
         _routesAndCallbacks.push([param1,param2]);
      }
      
      public function beat() : void
      {
         clearTimeout(_hb);
         _hb = 0;
         if(_socket && _socket.connected)
         {
            _socket.writeBytes(_package.encode(3));
            _socket.flush();
         }
      }
      
      private function send(param1:int, param2:String, param3:Object) : void
      {
         var _loc4_:ByteArray = null;
         _loc4_ = _message.encode(param1,param2,param3);
         _loc4_ = _package.encode(4,_loc4_);
         if(_socket && _socket.connected)
         {
            _socket.writeBytes(_loc4_);
            _socket.flush();
         }
      }
      
      private function onConnect(param1:Event) : void
      {
         _socket.writeBytes(_package.encode(1,Protocol.strencode(JSON.stringify(info))));
         _socket.flush();
      }
      
      private function onOutputProgress(param1:OutputProgressEvent) : void
      {
         trace("[Pomelo] flush ...");
      }
      
      private function onClose(param1:Event) : void
      {
         trace("[Pomelo] connect close ...");
         this.dispatchEvent(param1);
      }
      
      private function onIOError(param1:IOErrorEvent) : void
      {
         trace("[Pomelo] ",param1);
         this.dispatchEvent(param1);
      }
      
      private function onSecurityError(param1:SecurityErrorEvent) : void
      {
         trace("[Pomelo] ",param1);
         this.dispatchEvent(param1);
      }
      
      private function onData(param1:ProgressEvent) : void
      {
         var _loc3_:String = null;
         var _loc2_:Object = null;
         var _loc6_:* = undefined;
         var _loc5_:Object = null;
         var _loc4_:Object = null;
         _loc3_ = null;
         do
         {
            if(_pkg)
            {
               if(_socket.bytesAvailable >= _pkg.length)
               {
                  _pkg.body = new ByteArray();
                  if(_pkg.length)
                  {
                     _socket.readBytes(_pkg.body,0,_pkg.length);
                  }
               }
            }
            else
            {
               _pkg = _package.decode(_socket);
            }
            if(_pkg.body)
            {
               switch(_pkg.type)
               {
                  case 1:
                     _loc3_ = String(_pkg.body.readUTFBytes(_pkg.body.length));
                     _loc2_ = JSON.parse(_loc3_);
                     if(_loc2_.code == 200)
                     {
                        if(_loc2_.sys)
                        {
                           Routedic.init(_loc2_.sys.dict);
                           if(_loc6_ = _loc2_.sys.protos)
                           {
                              this.localData.writeSo(_loc6_);
                              Protobuf.init(_loc6_);
                           }
                           this.heartbeat = _loc2_.sys.heartbeat;
                           _socket.writeBytes(_package.encode(2));
                           _socket.flush();
                           this.dispatchEvent(new PomeloEvent("handshake"));
                        }
                     }
                     if(_handshake != null)
                     {
                        _handshake.call(this,_loc2_);
                     }
                     _pkg = null;
                     break;
                  case 2:
                     _pkg = null;
                     break;
                  case 3:
                     _pkg = null;
                     if(this.heartbeat)
                     {
                        _hb = setTimeout(beat,this.heartbeat * 1000);
                     }
                     break;
                  case 4:
                     if(!(_loc5_ = _message.decode(_pkg.body)).id)
                     {
                        this.dispatchEvent(new PomeloEvent(_loc5_.route,_loc5_.body));
                     }
                     else
                     {
                        try { controllers.battle.qc2.SimulateServerFrame.researchCaptureLoginSnapshot(requests[_loc5_.id].route,_loc5_.body); } catch(snapshotError:Error) { trace("Research snapshot: " + snapshotError); }
                        try { controllers.battle.qc2.SimulateServerFrame.researchManualResponse(requests[_loc5_.id].route,_loc5_.body); } catch(recordError:Error) { trace("Research recording: " + recordError); }
                        requests[_loc5_.id].callback.call(this,_loc5_.body);
                        requests[_loc5_.id] = null;
                     }
                     _pkg = null;
                     break;
                  case 5:
                     _loc4_ = {};
                     _loc3_ = String(_pkg.body.readUTFBytes(_pkg.body.length));
                     if(_loc3_)
                     {
                        _loc4_ = JSON.parse(_loc3_);
                     }
                     this.dispatchEvent(new PomeloEvent("kicked",_loc4_));
                     _pkg = null;
               }
            }
         }
         while(!_pkg && _socket && _socket.bytesAvailable > 4);
         
      }
      
      public function get message() : IMessage
      {
         return _message;
      }
      
      public function set message(param1:IMessage) : void
      {
         _message = param1;
      }
      
      public function destroy() : void
      {
         var _loc1_:int = 0;
         _loc1_ = _routesAndCallbacks.length - 1;
         while(_loc1_ >= 0)
         {
            this.removeEventListener(_routesAndCallbacks[_loc1_][0],_routesAndCallbacks[_loc1_][1]);
            _loc1_--;
         }
         _socket.removeEventListener("connect",onConnect);
         _socket.removeEventListener("close",onClose);
         _socket.removeEventListener("outputProgress",onOutputProgress);
         _socket.removeEventListener("socketData",onData);
         _socket.removeEventListener("ioError",onIOError);
         _socket.removeEventListener("securityError",onSecurityError);
      }
   }
}
